import logging
from typing import List, Literal, Optional, Sequence

import numpy as np
from anndata import AnnData
from scvi import REGISTRY_KEYS, settings
from scvi.data import AnnDataManager
from scvi.data.fields import (CategoricalObsField,
                              LayerField, NumericalJointObsField)
from scvi.model.base import BaseModelClass, UnsupervisedTrainingMixin, VAEMixin
from scvi.utils import setup_anndata_dsp

from drvi.scvi_tools_based._fields import FixedCategoricalJointObsField
from drvi.scvi_tools_based._module import DRVIModule
from drvi.scvi_tools_based._archesmixin import DRVIArchesMixin
from drvi.scvi_tools_based.merlin_data import (
    MerlinCategoricalJointObsField, MerlinCategoricalObsField, MerlinData,
    MerlinDataManager, MerlinDataSplitter, MerlinLayerField,
    MerlinNumericalJointObsField, MerlinTransformedDataLoader)
from drvi.module.feature_interface import FeatureInfoList

logger = logging.getLogger(__name__)


class DRVI(VAEMixin, DRVIArchesMixin, UnsupervisedTrainingMixin, BaseModelClass):
    """
    DRVI model based on scvi-tools skelethon

    Parameters
    ----------
    adata
        AnnData object that has been registered via :meth:`~mypackage.MyModel.setup_anndata`.
    n_latent
        Dimensionality of the latent space.
    encoder_dims
        Number of nodes in hidden layers of the encoder.
    decoder_dims
        Number of nodes in hidden layers of the decoder.
    prior
        Prior model. defaults to normal.
    prior_init_obs
        When initializing priors from data, these observations are used.
    categorical_covariates
        Categorical Covariates as a list of texts. You can specify emb dimension by appending @dim to each cpvariate.
    **model_kwargs
        Keyword args for :class:`~mypackage.MyModule`
    Examples
    --------
    >>> adata = anndata.read_h5ad(path_to_anndata)
    >>> drvi.DRVI.setup_anndata(adata, categorical_covariate_keys=["batch"])
    >>> vae = drvi.DRVI(adata)
    >>> vae.train()
    >>> adata.obsm["latent"] = vae.get_latent_representation()
    """

    def __init__(
            self,
            adata: AnnData | MerlinData,
            n_latent: int = 32,
            encoder_dims: Sequence[int] = tuple([128, 128]),
            decoder_dims: Sequence[int] = tuple([128, 128]),
            prior: Literal["normal", "gmm_x", "vamp_x"] = 'normal',
            prior_init_obs: Optional[np.ndarray] = None,
            categorical_covariates: List[str] = tuple([]),
            **model_kwargs,
    ):
        super().__init__(adata)

        # TODO: Remove later. Currently used to detect autoreload problems sooner.
        if isinstance(adata, MerlinData):
            self._data_splitter_cls = MerlinDataSplitter
        elif isinstance(adata, AnnData):
            pass
        else:
            raise ValueError("Only AnnData and MerlinData is supported")

        categorical_covariates_info = FeatureInfoList(categorical_covariates, axis='obs', default_dim=10)
        if REGISTRY_KEYS.CAT_COVS_KEY in self.adata_manager.data_registry:
            cat_cov_stats = self.adata_manager.get_state_registry(REGISTRY_KEYS.CAT_COVS_KEY)
            n_cats_per_cov = cat_cov_stats.n_cats_per_key
            assert tuple(categorical_covariates_info.names) == tuple(cat_cov_stats.field_keys)
        else:
            n_cats_per_cov = []
            assert len(categorical_covariates_info) == 0
        n_continuous_cov = self.summary_stats.get("n_extra_continuous_covs", 0)

        prior_init_dataloader = None
        if prior_init_obs is not None:
            assert "_" in prior
            assert len(prior_init_obs) == int(prior.split("_")[-1])
            prior_init_dataloader = self._make_data_loader(
                adata=adata[prior_init_obs],
                batch_size=len(prior_init_obs), shuffle=False)

        self.module = DRVIModule(
            n_input=self.summary_stats["n_vars"],
            n_latent=n_latent,
            encoder_dims=encoder_dims,
            decoder_dims=decoder_dims,
            n_cats_per_cov=n_cats_per_cov,
            n_continuous_cov=n_continuous_cov,
            prior=prior,
            prior_init_dataloader=prior_init_dataloader,
            categorical_covariate_dims=categorical_covariates_info.dims,
            **model_kwargs,
        )
        
        self._model_summary_string = (
            "DRVI \n"
            + (f"Covariates: {categorical_covariates_info.names}, \n" if len(categorical_covariates_info) > 0 else "") +
            f"Latent size: {self.module.n_latent}, "
            f"splits: {self.module.n_split_latent}, "
            f"pooling of splits: '{self.module.split_aggregation}', \n"
            f"Encoder dims: {encoder_dims}, \n"
            f"Decoder dims: {decoder_dims}, \n"
            f"Gene likelihood: {self.module.gene_likelihood}, \n"
        )
        # necessary line to get params that will be used for saving/loading
        self.init_params_ = self._get_init_params(locals())

        logger.info("The model has been initialized")

    @classmethod
    @setup_anndata_dsp.dedent
    def setup_anndata(
            cls,
            adata: AnnData,
            labels_key: Optional[str] = None,
            layer: Optional[str] = None,
            is_count_data: bool = True,
            categorical_covariate_keys: Optional[List[str]] = None,
            continuous_covariate_keys: Optional[List[str]] = None,
            **kwargs,
    ) -> None:
        """
        %(summary)s.

        Parameters
        ----------
        %(param_adata)s
        %(param_labels_key)s
        %(param_layer)s
        %(param_cat_cov_keys)s
        %(param_cont_cov_keys)s
        Returns
        -------
        %(returns)s
        """
        setup_method_args = cls._get_setup_method_args(**locals())
        anndata_fields = [
            LayerField(REGISTRY_KEYS.X_KEY, layer, is_count_data=is_count_data),
            CategoricalObsField(REGISTRY_KEYS.LABELS_KEY, labels_key),
            FixedCategoricalJointObsField(REGISTRY_KEYS.CAT_COVS_KEY, categorical_covariate_keys),
            NumericalJointObsField(REGISTRY_KEYS.CONT_COVS_KEY, continuous_covariate_keys),
        ]
        adata_manager = AnnDataManager(fields=anndata_fields, setup_method_args=setup_method_args)
        adata_manager.register_fields(adata, **kwargs)
        cls.register_manager(adata_manager)

    @classmethod
    def setup_merlin_data(
        cls,
        merlin_data: MerlinData,
        labels_key: Optional[str] = None,
        layer: str = 'X',
        is_count_data: bool = True,
        categorical_covariate_keys: Optional[List[str]] = None,
        continuous_covariate_keys: Optional[List[str]] = None,
        **kwargs
    ):
        setup_method_args = cls._get_setup_method_args(**locals())

        fields = [
            MerlinLayerField(REGISTRY_KEYS.X_KEY, layer, is_count_data=is_count_data),
            MerlinCategoricalObsField(REGISTRY_KEYS.LABELS_KEY, labels_key),
            MerlinCategoricalJointObsField(REGISTRY_KEYS.CAT_COVS_KEY, categorical_covariate_keys),
            MerlinNumericalJointObsField(REGISTRY_KEYS.CONT_COVS_KEY, continuous_covariate_keys),
        ]
        merlin_manager = MerlinDataManager(fields, setup_method_args=setup_method_args)
        merlin_manager.register_fields(merlin_data, **kwargs)
        cls.register_manager(merlin_manager)

    def _make_data_loader(
        self,
        adata,
        indices: Optional[Sequence[int]] = None,
        batch_size: Optional[int] = None,
        shuffle: bool = False,
        data_loader_class=None,
        **data_loader_kwargs,
    ):
        """Create a AnnDataLoader object for data iteration.

        Parameters
        ----------
        adata
            AnnData or MerlinData object with equivalent structure to initial AnnData.
        indices
            Indices of cells in adata to use. If `None`, all cells are used.
        batch_size
            Minibatch size for data loading into model. Defaults to `scvi.settings.batch_size`.
        shuffle
            Whether observations are shuffled each iteration though
        data_loader_class
            Class to use for data loader
        data_loader_kwargs
            Kwargs to the class-specific data loader class
        """
        if isinstance(adata, AnnData):
            return super()._make_data_loader(
                adata, indices, batch_size, shuffle, data_loader_class, **data_loader_kwargs
            )
        elif isinstance(adata, MerlinData):
            adata_manager = self.get_anndata_manager(adata)
            if adata_manager is None:
                raise AssertionError(
                    "AnnDataManager not found. Call `self._validate_anndata` prior to calling this function."
                )
            if batch_size is None:
                batch_size = settings.batch_size
            return MerlinTransformedDataLoader(
                self.adata_manager.get_dataset('default'),
                mapping=self.adata_manager.get_fields_schema_mapping(),
                batch_size=batch_size,
                shuffle=shuffle,
                parts_per_chunk=1,
                **data_loader_kwargs,
            )
        else:
            raise ValueError("Only AnnData and MerlinData is supported")
