import pytest
import torch

import tests.base.utils as tutils
from pytorch_lightning import Trainer
from pytorch_lightning.utilities.exceptions import MisconfigurationException
from tests.base import EvalModelTemplate
from torch.utils.data import RandomSampler, SequentialSampler, DataLoader


def test_overfit(tmpdir):

    # ------------------------------------------------------
    # Make sure shuffle is correct across loaders initially
    # ------------------------------------------------------
    model = EvalModelTemplate()
    model.train_dataloader()

    # original train loader which should be replaced in all methods
    train_loader = model.train_dataloader()

    # make sure the val and tests are not shuffled
    assert isinstance(train_loader.sampler, RandomSampler)
    assert isinstance(model.val_dataloader().sampler, SequentialSampler)
    assert isinstance(model.test_dataloader().sampler, SequentialSampler)

    # ------------------------------------------------------
    # get the training loader and batch
    # ------------------------------------------------------
    train_loader = DataLoader(model.train_dataloader().dataset, shuffle=False)
    full_train_samples = len(train_loader)
    num_train_samples = int(0.11 * full_train_samples)

    (xa, ya) = next(iter(train_loader))

    # ------------------------------------------------------
    # set VAL and Test loaders
    # ------------------------------------------------------
    val_loader = DataLoader(model.val_dataloader().dataset, shuffle=False)
    test_loader = DataLoader(model.test_dataloader().dataset, shuffle=False)

    # set the model loaders
    model.train_dataloader = lambda: train_loader
    model.val_dataloader = lambda: val_loader
    model.test_dataloader = lambda: test_loader

    # ------------------------------------------------------
    # run tests for both val and test
    # ------------------------------------------------------
    for split in ['val', 'test']:

        # ------------------------------------------------------
        # test overfit_batches as percent
        # ------------------------------------------------------
        loader_num_batches, dataloaders = Trainer(overfit_batches=0.11)._reset_eval_dataloader(model, split)
        assert loader_num_batches[0] == num_train_samples

        # make sure we turned off shuffle for the user
        assert isinstance(dataloaders[0].sampler, SequentialSampler)

        # make sure the loaders are the same
        (xb, yb) = next(iter(dataloaders[0]))
        assert torch.eq(xa, xb).all()
        assert torch.eq(ya, yb).all()

        # ------------------------------------------------------
        # test overfit_batches as int
        # ------------------------------------------------------
        loader_num_batches, dataloaders = Trainer(overfit_batches=1)._reset_eval_dataloader(model, split)
        assert loader_num_batches[0] == 1
        loader_num_batches, dataloaders = Trainer(overfit_batches=5)._reset_eval_dataloader(model, split)
        assert loader_num_batches[0] == 5

        # ------------------------------------------------------
        # test limit_xxx_batches as percent AND int
        # ------------------------------------------------------
        if split == 'val':
            loader_num_batches, dataloaders = Trainer(limit_val_batches=0.1)._reset_eval_dataloader(model, split)
            assert loader_num_batches[0] == int(0.1 * len(val_loader))

            loader_num_batches, dataloaders = Trainer(limit_val_batches=10)._reset_eval_dataloader(model, split)
            assert loader_num_batches[0] == 10
        else:
            loader_num_batches, dataloaders = Trainer(limit_test_batches=0.1)._reset_eval_dataloader(model, split)
            assert loader_num_batches[0] == int(0.1 * len(test_loader))

            loader_num_batches, dataloaders = Trainer(limit_test_batches=10)._reset_eval_dataloader(model, split)
            assert loader_num_batches[0] == 10


def test_model_reset_correctly(tmpdir):
    """ Check that model weights are correctly reset after scaling batch size. """
    tutils.reset_seed()

    model = EvalModelTemplate()

    # logger file to get meta
    trainer = Trainer(
        default_root_dir=tmpdir,
        max_epochs=1
    )

    before_state_dict = model.state_dict()

    trainer.scale_batch_size(model, max_trials=5)

    after_state_dict = model.state_dict()

    for key in before_state_dict.keys():
        assert torch.all(torch.eq(before_state_dict[key], after_state_dict[key])), \
            'Model was not reset correctly after scaling batch size'


def test_trainer_reset_correctly(tmpdir):
    """ Check that all trainer parameters are reset correctly after scaling batch size. """
    tutils.reset_seed()

    model = EvalModelTemplate()

    # logger file to get meta
    trainer = Trainer(
        default_root_dir=tmpdir,
        max_epochs=1
    )

    changed_attributes = ['max_steps',
                          'weights_summary',
                          'logger',
                          'callbacks',
                          'checkpoint_callback',
                          'early_stop_callback',
                          'enable_early_stop',
                          'train_percent_check']

    attributes_before = {}
    for ca in changed_attributes:
        attributes_before[ca] = getattr(trainer, ca)

    trainer.scale_batch_size(model, max_trials=5)

    attributes_after = {}
    for ca in changed_attributes:
        attributes_after[ca] = getattr(trainer, ca)

    for key in changed_attributes:
        assert attributes_before[key] == attributes_after[key], \
            f'Attribute {key} was not reset correctly after learning rate finder'


@pytest.mark.parametrize('scale_arg', ['power', 'binsearch'])
def test_trainer_arg(tmpdir, scale_arg):
    """ Check that trainer arg works with bool input. """
    tutils.reset_seed()

    hparams = EvalModelTemplate.get_default_hparams()
    model = EvalModelTemplate(**hparams)

    before_batch_size = hparams.get('batch_size')
    # logger file to get meta
    trainer = Trainer(
        default_root_dir=tmpdir,
        max_epochs=1,
        auto_scale_batch_size=scale_arg,
    )

    trainer.fit(model)
    after_batch_size = model.batch_size
    assert before_batch_size != after_batch_size, \
        'Batch size was not altered after running auto scaling of batch size'


@pytest.mark.parametrize('scale_method', ['power', 'binsearch'])
def test_call_to_trainer_method(tmpdir, scale_method):
    """ Test that calling the trainer method itself works. """
    tutils.reset_seed()

    hparams = EvalModelTemplate.get_default_hparams()
    model = EvalModelTemplate(**hparams)

    before_batch_size = hparams.get('batch_size')
    # logger file to get meta
    trainer = Trainer(
        default_root_dir=tmpdir,
        max_epochs=1,
    )

    after_batch_size = trainer.scale_batch_size(model, mode=scale_method, max_trials=5)
    model.batch_size = after_batch_size
    trainer.fit(model)

    assert before_batch_size != after_batch_size, \
        'Batch size was not altered after running auto scaling of batch size'


def test_error_on_dataloader_passed_to_fit(tmpdir):
    """Verify that when the auto scale batch size feature raises an error
       if a train dataloader is passed to fit """

    # only train passed to fit
    model = EvalModelTemplate()
    trainer = Trainer(
        default_root_dir=tmpdir,
        max_epochs=1,
        limit_val_batches=0.1,
        train_percent_check=0.2,
        auto_scale_batch_size='power'
    )
    fit_options = dict(train_dataloader=model.dataloader(train=True))

    with pytest.raises(MisconfigurationException):
        trainer.fit(model, **fit_options)
