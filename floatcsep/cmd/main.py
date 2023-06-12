from floatcsep import __version__
from floatcsep.experiment import Experiment
import logging
import argparse
log = logging.getLogger(__name__)


def stage(config, **_):

    log.info(f'Running floatCSEP v{__version__} | Stage')
    exp = Experiment.from_yml(config)
    exp.stage_models()
    log.info('Finalized\n')


def run(config, show=True):

    log.info(f'Running floatCSEP v{__version__} | Run')
    exp = Experiment.from_yml(config)
    exp.stage_models()
    exp.set_tasks()
    exp.run()
    if show:
        exp.plot_results()
        exp.plot_forecasts()
        exp.generate_report()
    exp.make_repr()

    log.info('Finalized\n')


def plot(config, **_):

    log.info(f'Running floatCSEP v{__version__} | Plot')
    exp = Experiment.from_yml(config)
    exp.stage_models()
    exp.set_tasks()
    exp.plot_results()
    exp.plot_forecasts()
    exp.generate_report()
    log.info('Finalized\n')

    return exp


def reproduce(config, **_):

    log.info(f'Running floatCSEP v{__version__} | Reproduce')
    reproduced_exp = Experiment.from_yml(config, reprdir='reproduced')
    reproduced_exp.stage_models()
    reproduced_exp.set_tasks()
    reproduced_exp.run()

    original_config = reproduced_exp.original_config
    original_exp = Experiment.from_yml(original_config)
    original_exp.stage_models()
    original_exp.set_tasks()

    log.info('Finalized\n')


def floatcsep():

    parser = argparse.ArgumentParser(argument_default=argparse.SUPPRESS)
    parser.add_argument('func', type=str, choices=['run', 'stage',
                                                   'plot', 'reproduce'],
                        help='Run a calculation')
    parser.add_argument('config', type=str,
                        help='Experiment Configuration file')
    parser.add_argument('-s', '--show', type=str,
                        help='Use saved results', default=True)

    args = parser.parse_args()
    try:
        func = globals()[args.func]
        args.__delattr__('func')

    except AttributeError:
        raise AttributeError('Function not implemented')
    func(**vars(args))
