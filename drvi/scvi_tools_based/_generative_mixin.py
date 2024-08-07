import logging
from typing import Callable, Optional, Sequence

import numpy as np
import scvi
import torch
from anndata import AnnData
from torch.nn import functional as F

logger = logging.getLogger(__name__)


class GenerativeMixin:
    """Mixins to interpret generative part of the method."""

    @torch.inference_mode()
    def iterate_on_decoded_latent_samples(
        self,
        z: np.ndarray, 
        step_func: Callable,
        aggregation_func: Callable,
        lib: Optional[np.ndarray] = None,
        cat_key: Optional[np.ndarray] = None,
        cont_key: Optional[np.ndarray] = None, 
        batch_size = scvi.settings.batch_size,
    ) -> np.ndarray:
        r"""iterate over decoder outputs and aggregate the results.

        Parameters
        ----------
        z
            Latent samples.
        step_func
            Function to apply to the decoder output at each step.
            generative_outputs and a store variable are given to the function
        aggregation_func
            Function to aggregate the step results.
        lib
            Library size array.
        cat_key
            Categorical covariates (required if model has categorical key).
        cont_key
            Continuous covariates.
        batch_size
            Minibatch size for data loading into model. Defaults to `scvi.settings.batch_size`.
        """
        store = []
        self.module.eval()

        with torch.no_grad():
            for i in np.arange(0, z.shape[0], batch_size):
                slice = np.arange(i, min(i + batch_size, z.shape[0]))
                z_tensor = torch.tensor(z[slice])
                if lib is None:
                    lib_tensor = torch.tensor([1e4] * slice.shape[0])
                else:
                    lib_tensor = torch.tensor(lib[slice])
                cat_tensor = torch.tensor(cat_key[slice]) if cat_key is not None else None
                batch_tensor = None
                
                gen_input = self.module._get_generative_input(
                    tensors={
                        scvi.REGISTRY_KEYS.BATCH_KEY: batch_tensor,
                        scvi.REGISTRY_KEYS.LABELS_KEY: None,
                        scvi.REGISTRY_KEYS.CONT_COVS_KEY: torch.log(lib_tensor).unsqueeze(-1) if self.summary_stats.get("n_extra_continuous_covs", 0) == 1 else None,
                        scvi.REGISTRY_KEYS.CAT_COVS_KEY: cat_tensor,
                    },
                    inference_outputs={
                        'z': z_tensor,
                        'library': lib_tensor,
                        'gene_likelihood_additional_info': {},
                    },
                )
                gen_output = self.module.generative(**gen_input)
                step_func(gen_output, store)
        result = aggregation_func(store)
        return result


    @torch.inference_mode()
    def decode_latent_samples(
        self,
        z: np.ndarray, 
        lib: Optional[np.ndarray] = None,
        cat_key: Optional[np.ndarray] = None,
        cont_key: Optional[np.ndarray] = None, 
        batch_size = scvi.settings.batch_size,
    ) -> np.ndarray:
        r"""Return the distribution produces by the decoder for the given latent samples.

        This is typically considered as :math:`p(x \mid z)`.

        Parameters
        ----------
        z
            Latent samples.
        lib
            Library size array.
        cat_key
            Categorical covariates (required if model has categorical key).
        cont_key
            Continuous covariates.
        batch_size
            Minibatch size for data loading into model. Defaults to `scvi.settings.batch_size`.
        return_mean
            Return the mean of the distribution or the full distribution.
        """
        step_func = lambda gen_output, store: store.append(gen_output['params']['mean'].detach().cpu())
        aggregation_func = lambda store: torch.cat(store, dim=0).numpy(force=True)

        return self.iterate_on_decoded_latent_samples(
            z=z,
            step_func=step_func,
            aggregation_func=aggregation_func,
            lib=lib,
            cat_key=cat_key,
            cont_key=cont_key,
            batch_size=batch_size,
        )
    

    @torch.inference_mode()
    def iterate_on_ae_output(
        self,
        adata: AnnData,
        step_func: Callable,
        aggregation_func: Callable,
        indices: Optional[Sequence[int]] = None,
        batch_size: Optional[int] = None,
        deterministic: bool = False,
    ) -> np.ndarray:
        r"""iterate over autoencoder outputs and aggregate the results.

        Parameters
        ----------
        adata
            AnnData object with equivalent structure to initial AnnData.
            If `None`, defaults to the AnnData object used to initialize the model.
        step_func
            Function to apply to the autoencoder output at each step.
            inference_outputs, generative_outputs, losses, and a store variable are given to the function
        aggregation_func
            Function to aggregate the step results.
        indices
            Indices of cells in adata to use. If `None`, all cells are used.
        batch_size
            Minibatch size for data loading into model. Defaults to `scvi.settings.batch_size`.
        deterministic
            Makes model fully deterministic (e.g. no sampling in the bottleneck).
        """
        adata = self._validate_anndata(adata)
        data_loader = self._make_data_loader(
            adata=adata, indices=indices, batch_size=batch_size
        )
        
        store = []
        try:
            if deterministic:
                self.module.fully_deterministic = True
            for tensors in data_loader:
                loss_kwargs = {"kl_weight": 1}
                inference_outputs, generative_outputs, losses = self.module(tensors, loss_kwargs=loss_kwargs)
                step_func(inference_outputs, generative_outputs, losses, store)
        except Exception as e:
            logger.error(f"An error occurred in the iteration: {e}")
            pass
        finally:
            self.module.fully_deterministic = False
        
        return aggregation_func(store)
    

    @torch.inference_mode()
    def get_reconstruction_effect_of_each_split(
        self,
        adata: Optional[AnnData] = None,
        aggregate_over_cells: bool = True,
        deterministic: bool = True,
        **kwargs,
    ) -> np.ndarray:
        r"""Return the effect of each split on the reconstructed per sample.

        Parameters
        ----------
        adata
            AnnData object with equivalent structure to initial AnnData.
            If `None`, defaults to the AnnData object used to initialize the model.
        aggregate_over_cells
            Whether to aggregate the effect over cells and return a value per dimension.
        deterministic
            Makes model fully deterministic (e.g. no sampling in the bottleneck).
        kwargs
            Additional keyword arguments for the `iterate_on_ae_output` method.
        """
        def calculate_effect(inference_outputs, generative_outputs, losses, store):
            if self.module.split_aggregation == "logsumexp":
                effect_share = F.softmax(generative_outputs['original_params']['mean'], dim=-2)
            elif self.module.split_aggregation == "sum":
                effect_share = F.normalize(torch.abs(generative_outputs['original_params']['mean']), p=1, dim=-2)
            else:
                raise NotImplementedError("Only logsumexp and sum aggregations are supported for now.")
            mean_in_log_space = F.softplus(generative_outputs['params']['mean'])  # log(1+exp(x)) for negative values in log-space
            effect_share = (effect_share * mean_in_log_space.unsqueeze(-2)).sum(dim=-1)
            return store.append(effect_share.detach().cpu())

        def aggregate_effects(store):
            return torch.cat(store, dim=0).numpy(force=True)

        output = self.iterate_on_ae_output(
            adata=adata,
            step_func=calculate_effect,
            aggregation_func=aggregate_effects,
            deterministic=deterministic,
            **kwargs,
        )

        if aggregate_over_cells:
            output = output.mean(axis=0)
        
        return output


    # @torch.inference_mode()
    def get_max_effect_of_splits_within_distribution(
        self,
        adata: Optional[AnnData] = None,
        deterministic: bool = True,
        **kwargs,
    ):
        r"""Return the max effect of each split on the reconstructed expression params for all genes.
        These values are empirical and inexact for de reasoning of dimensions.

        Parameters
        ----------
        adata
            AnnData object with equivalent structure to initial AnnData.
            If `None`, defaults to the AnnData object used to initialize the model.
        deterministic
            Makes model fully deterministic (e.g. no sampling in the bottleneck).
        kwargs
            Additional keyword arguments for the `iterate_on_ae_output` method.
        """
        def calculate_effect(inference_outputs, generative_outputs, losses, store):
            # if self.module.split_aggregation == "logsumexp":
            #     effect_logfc = -torch.log10(1 - F.softmax(generative_outputs['original_params']['mean'], dim=-2))
            # elif self.module.split_aggregation == "sum":
            #     effect_logfc = -torch.log10(1 - F.normalize(generative_outputs['original_params']['mean'], p=1, dim=-2))
            # else:
            #     raise NotImplementedError("Only logsumexp and sum aggregations are supported for now.")
            if self.module.split_aggregation == "logsumexp":
                effect_share = F.softmax(generative_outputs['original_params']['mean'], dim=-2)
            elif self.module.split_aggregation == "sum":
                effect_share = F.normalize(torch.abs(generative_outputs['original_params']['mean']), p=1, dim=-2)
            else:
                raise NotImplementedError("Only logsumexp and sum aggregations are supported for now.")
            mean_in_log_space = F.softplus(generative_outputs['params']['mean'])  # log(1+exp(x)) for negative values in log-space
            effect_share = (effect_share * mean_in_log_space.unsqueeze(-2)).amax(dim=0).detach().cpu().numpy(force=True)
            if len(store) == 0:
                store.append(effect_share)
            else:
                store[0] = np.maximum(store[0], effect_share)

        def aggregate_effects(store):
            return store
        
        output = self.iterate_on_ae_output(
            adata=adata,
            step_func=calculate_effect,
            aggregation_func=aggregate_effects,
            deterministic=deterministic,
            **kwargs,
        )
        
        return output
