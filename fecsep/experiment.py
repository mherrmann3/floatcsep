import os
import os.path
from collections.abc import Mapping, Sequence
from typing import Union, List, Tuple, Callable
from functools import singledispatchmethod
import numpy
import yaml
import json
from datetime import datetime
from matplotlib import pyplot
from cartopy import crs as ccrs

from csep.models import EvaluationResult
from csep.core.catalogs import CSEPCatalog
from csep.utils.time_utils import decimal_year
from csep.core.forecasts import GriddedForecast

from fecsep import report
from fecsep.registry import register
from fecsep.utils import NoAliasLoader, parse_csep_func, read_time_config, \
    read_region_config, Task, timewindow2str, str2timewindow
from fecsep.model import Model
from fecsep.evaluation import Evaluation
import warnings
import csep

numpy.seterr(all="ignore")
warnings.filterwarnings("ignore")


class Experiment:
    """

    Main class that handles an Experiment's context. Contains all the
    specifications, instructions and methods to carry out an experiment.

    Args:
        name (str): Experiment name
        path (str): Experiment working directory. All artifacts relative paths'
                    are defined from here (e.g. model files, source code,
                    catalog files, etc.)
        time_config (dict): Contains all the temporal specifications.
            It can contain the following keys:

            - start_date (:class:`datetime.datetime`):
              Experiment start date
            - end_date (:class:`datetime.datetime`):
              Experiment end date
            - exp_class (:class:`str`):
              `ti` (Time-Independent) or `td` (Time-Dependent)
            - intervals (:class:`int`): Number of testing intervals/windows
            - horizon (:class:`str`, :py:class:`float`): Time length of the
              forecasts (e.g. 1, 10, `1 year`, `2 days`). `ti` defaults to
              years, `td` to days.
            - growth (:class:`str`): `incremental` or `cumulative`
            - offset (:class:`float`): recurrence of forecast creation.

            For further details, see :func:`~fecsep.utils.timewindows_ti` and
            :func:`~fecsep.utils.timewindows_td`

        region_config (dict): Contains all the spatial and magnitude
            specifications. It must contain the following keys:

            - region (:py:class:`str`,
              :class:`csep.core.regions.CartesianGrid2D`): The geographical
              region, specified as:
              (i) the name of a :mod:`csep`/:mod:`fecsep` default region
              function (e.g. :func:`~csep.core.regions.california_relm_region`)
              (ii) the name of a user function or
              (iii) the path to a lat/lon file
            - mag_min (:class:`float`): Minimum magnitude of the experiment
            - mag_max (:class:`float`): Maximum magnitude of the experiment
            - mag_bin (:class:`float`): Magnitud bin size
            - magnitudes (:class:`list`, :class:`numpy.ndarray`): Explicit
              magnitude bins
            - depth_min (:class:`float`): Minimum depth. Defaults to -2
            - depth_max (:class:`float`): Maximum depth. Defaults to 6000

        model_config (str): Path to the models' configuration file
        test_config (str): Path to the evaluations' configuration file
        default_test_kwargs (dict): Default values for the testing
         (seed, number of simulations, etc.)
        postproc_config (dict): Contains the instruction for postprocessing
         (e.g. plot forecasts, catalogs)
        **kwargs: see Note

    Note:
        Instead of using `time_config` and `region_config`, an Experiment can
        be instantiated using these dicts as keywords. (e.g. ``Experiment(
        **time_config, **region_config)``, ``Experiment(start_date=start_date,
        intervals=1, region='csep-italy', ...)``

    """

    '''
    Data management
    
    Model:
        - FILE   - read from file, scale in runtime             
                 - drop to db, scale from function in runtime   
        - CODE  - run, read from file              
                - run, store in db, read from db   
    
    TEST:
        - use forecast from runtime
        - read forecast from file (TD)
          (does not make sense for TI (too much FS space) unless is already
           dropped to DB)
    '''

    @register
    def __init__(self,
                 name: str = None,
                 time_config: dict = None,
                 region_config: dict = None,
                 catalog: str = None,
                 model_config: str = None,
                 test_config: str = None,
                 postproc_config: str = None,
                 default_test_kwargs: dict = None,
                 **kwargs) -> None:
        # todo
        #  - instantiate from full experiment register (ignoring test/models
        #  config), or self-awareness functions?
        #  - instantiate as python objects (rethink models/tests config)
        #  - check if model region matches experiment region for nonQuadTree?
        #    Or filter region
        # Instantiate
        self.name = name if name else 'floatingExp'
        self.path = kwargs.get('path') if kwargs.get('path',
                                                     None) else os.getcwd()

        self.time_config = read_time_config(time_config, **kwargs)
        self.region_config = read_region_config(region_config, **kwargs)
        # todo: make it simple and also load catalog as file if given:
        self.catalog = catalog

        self.model_config = model_config
        self.test_config = test_config
        self.postproc_config = postproc_config if postproc_config else {}
        self.default_test_kwargs = default_test_kwargs

        # Initialize class attributes
        self.models = []
        self.tests = []

        self.tasks = []
        self.run_results = {}
        # self.catalog = None
        self.run_folder: str = ''
        self._paths: dict = {}
        self._exists: dict = {}

        # Update if attributes were passed explicitly
        # todo check reinstantiation
        # self.__dict__.update(**kwargs)

    def __getattr__(self, item: str) -> object:
        # Gets time_config and region_config keys as Experiment's attribute
        try:
            return self.__dict__[item]
        except KeyError:
            try:
                return self.time_config[item]
            except KeyError:
                try:
                    return self.region_config[item]
                except KeyError:
                    raise AttributeError(
                        f"Experiment '{self.name}'"
                        f" has no attribute '{item}'") from None

    def __dir__(self):
        # todo add timewindows
        # Adds time and region configs keys to instance scope
        _dir = list(super().__dir__()) + list(self.time_config.keys()) + list(
            self.region_config)
        return sorted(_dir)

    def _abspath(self, *paths: Sequence[str]) -> Tuple[str, str]:
        """ Gets the absolute path of a file, when it was defined relative to the
        experiment working dir."""
        # todo check redundancy when passing an actual absolute path (e.g.
        #  when re-instantiating). Pass to self.Registry()
        _path = os.path.normpath(
            os.path.abspath(os.path.join(self.path, *paths)))
        _dir = os.path.dirname(_path)
        return _dir, _path

    def stage_models(self) -> None:
        """ Stages all the experiment's models"""
        for i in self.models:
            i.stage()

    def add_model(self, model_i: dict) -> None:
        """ Add experiment reg to Model class, to share between model
        instances """

        model = Model.from_dict(model_i)
        self.reg.add_reg(model.reg)
        self.models.append(model)

    def set_models(self) -> None:
        """

        Parse the models' configuration file/dict. Instantiates all the models
        as :class:`fecsep.model.Model` and store them into :attr:`self.models`.

        """
        # todo: handle when model cfg is a dict instead of a file.

        _dir, modelcfg_path = self._abspath(self.model_config)

        with open(modelcfg_path, 'r') as file_:
            config_dict = yaml.load(file_, NoAliasLoader)

        for element in config_dict:
            # Check if the model is unique or has multiple submodels
            if not any('flavours' in i for i in element.values()):

                name_ = next(iter(element))
                # updates path to absolute
                model_abspath = self._abspath(_dir, element[name_]['path'])[1]
                model_i = {name_: {**element[name_], 'path': model_abspath}}
                self.add_model(model_i)
            else:
                model_flavours = list(element.values())[0]['flavours'].items()
                for flav, flav_path in model_flavours:
                    name_super = next(iter(element))
                    # updates path to absolute
                    path_super = element[name_super].get('path', '')
                    path_sub = self._abspath(_dir, path_super, flav_path)[1]
                    # updates name of submodel
                    name_flav = f'{name_super}@{flav}'
                    model_ = {name_flav: {**element[name_super],
                                          'path': path_sub}}
                    model_[name_flav].pop('flavours')
                    self.add_model(model_)

        # Checks if there is any repeated model.
        names_ = [i.name for i in self.models]
        if len(names_) != len(set(names_)):
            reps = set(
                [i for i in names_ if (sum([j == i for j in names_]) > 1)])
            one = not bool(len(reps) - 1)
            print(f'Warning: Model{"s" * (not one)} {reps}'
                  f' {"is" * one + "are" * (not one)} repeated')

    def add_evaluation(self, eval_i: dict) -> None:
        """ Add evaluation to Experiment class, and share the registry
        """

        evaluation = Evaluation.from_dict(eval_i)
        self.reg.add_reg(evaluation.reg)
        self.tests.append(evaluation)

    def set_tests(self) -> None:
        """
        Parse the tests' configuration file/dict. Instantiate them as
        :class:`fecsep.test.Test` and store them into :attr:`self.tests`.

        """

        with open(self._abspath(self.test_config)[1], 'r') as config:
            config_dict = yaml.load(config, NoAliasLoader)

        for evaldict in config_dict:
            self.add_evaluation(evaldict)

    def prepare_paths(self, results_path: str = None,
                      run_name: str = None) -> None:
        """

        Creates the run directory, and reads the file structure inside

        Args:
            results_path: path to store
            run_name: name of run

        Returns:
            run_folder: Path to the run.
             exists: flag if forecasts, catalogs and test_results if they
             exist already
             target_paths: flag to each element of the gefe (catalog and
             evaluation results)

        """

        # grab names for creating directories
        windows = timewindow2str(self.timewindows)
        models = [i.name for i in self.models]
        tests = [i.name for i in self.tests]

        # todo create datetime parser for filenames
        if run_name is None:
            run_name = 'run'
            # todo find better way to name paths
            # run_name = f'run_{datetime.now().date().isoformat()}'

        # Determine required directory structure for run
        # results > test_date > time_window > cats / evals / figures

        self.run_folder = self._abspath(results_path or 'results', run_name)[1]
        subfolders = ['catalog', 'evaluations', 'figures', 'forecasts']

        dirtree = {
            win: {folder: self._abspath(self.run_folder, win, folder)[1] for
                  folder
                  in subfolders} for win in windows}

        # create directories if they don't exist
        for tw, tw_folder in dirtree.items():
            for _, folder_ in tw_folder.items():
                os.makedirs(folder_, exist_ok=True)

        # Check existing files
        files = {win: {name: list(os.listdir(path)) for name, path in
                       windir.items()} for win, windir in dirtree.items()}

        exists = {win: {
            'forecasts': False,
            # todo Modify for time-dependent, and/or forecast storage
            'catalog': any(file for file in files[win]['catalog']),
            'evaluations': {
                test: {
                    model: any(f'{test}_{model}.json' in file for file in
                               files[win]['evaluations'])
                    for model in models
                }
                for test in tests
            }
        } for win in windows}

        target_paths = {win: {
            'models': {  # todo: redo this key, is too convoluted
                'forecasts': {
                    model_name: model_name
                    for model_name in models},
                # todo: important in time-dependent, and/or forecast storage
                'figures': {model: os.path.join(dirtree[win]['figures'],
                                                f'{model}')
                            for model in models}},
            'catalog': os.path.join(dirtree[win]['catalog'], 'catalog.json'),
            'evaluations': {
                test: {
                    model: os.path.join(dirtree[win]['evaluations'],
                                        f'{test}_{model}.json')
                    for model in models
                }
                for test in tests
            },
            'figures': {test: os.path.join(dirtree[win]['figures'], f'{test}')
                        for test in tests}
        } for win in windows}

        self.run_folder = self.run_folder
        self._paths = target_paths
        self._exists = exists  # todo perhaps method?

    def prepare_subcatalog(self, tstring: str) -> None:
        """

        Filters the experiment catalog to a single time window and writes it
        in the corresponding directory.

        Args:
            tstring (str): Time window string

        """
        start, end = str2timewindow(tstring)
        subcat = self.catalog.filter(
            [f'origin_time < {end.timestamp() * 1000}',
             f'origin_time >= {start.timestamp() * 1000}'])
        subcat.write_json(filename=self._paths[tstring]['catalog'])

    # def prepare_tasks(self):
    #
    #     tasks = []
    #     tw_strings = timewindow2str(self.timewindows)
    #     # Prepare testing catalogs
    #
    #     for time_str in tw_strings:
    #         task_i = Task(instance=self, method='prepare_subcatalog',
    #                       tstring=time_str)
    #         tasks.append(task_i)
    #
    #     # Prepare input catalogs for time-dependent
    #
    #     # Create Forecasts
    #     for i, time_str in enumerate(tw_strings):
    #         for model_j in self.models:
    #             task_ij = Task(instance=model_j, method='create_forecast',
    #                            tstring=time_str, prenode=i)
    #             tasks.append(task_ij)
    #     tasks_idx = {**{i: n for n, i in enumerate(tw_strings)},
    #                  **{(i, j): n + len(tw_strings) for n, (i, j) in
    #                     enumerate(itertools.product(tw_strings, self.models))}}
    #
    #     # Compute tests
    #     for test in self.tests:
    #         # Consistency tests
    #         if 'Discrete' in test.type and 'Absolute' in test.type:
    #             for time_str in enumerate(tw_strings):
    #                 for model_j in enumerate(self.models):
    #                     task_ijk = Task(
    #                         instance=test,
    #                         method='compute',
    #                         prenode=(tasks_idx[time_str],
    #                                  tasks_idx[(time_str, model_j)]),
    #                         timewindow=time_str,
    #                         catalog=self._paths[time_str]['catalog'],
    #                         model=model_j,
    #                         path=self._paths[time_str][
    #                             'evaluations'][test.name][model_j.name])
    #                     tasks.append(task_ijk)
    #
    #         # Comparative Tests
    #         elif 'Discrete' in test.type and 'Comparative' in test.type:
    #             for time_str in enumerate(tw_strings):
    #                 for model_j in self.models:
    #                     task_ik = Task(
    #                         instance=test,
    #                         method='compute',
    #                         prenode=(tasks_idx[time_str],
    #                                  tasks_idx[(time_str, model_j)],
    #                                  tasks_idx[(time_str,
    #                                             self.get_model(test.ref_model))]),
    #                         timewindow=time_str,
    #                         catalog=self._paths[time_str]['catalog'],
    #                         model=model_j,
    #                         ref_model=self.get_model(test.ref_model),
    #                         path=self._paths[time_str][
    #                             'evaluations'][test.name][model_j.name]
    #                     )
    #                     tasks.append(task_ik)
    #
    #         elif 'Sequential' in test.type and 'Absolute' in test.type:
    #             for model_j in self.models:
    #                 task_k = Task(
    #                     instance=test,
    #                     method='compute',
    #                     prenode=(*[tasks_idx[i] for i in tw_strings],
    #                              *[*tasks_idx[(i, j)]) f],
    #                     timewindow=tw_strings,
    #                     catalog=[self._paths[i]['catalog'] for i in
    #                              tw_strings],
    #                     model=model_j,
    #                     path=self._paths[tw_strings[-1]][
    #                         'evaluations'][test.name][model_j.name]
    #                 )
    #                 tasks.append(task_k)
    #         elif 'Comparative' in test_k.type:
    #             timestrs = timewindow2str(self.timewindows)
    #             for model_j in self.models:
    #                 task_k = Task(
    #                     instance=test_k,
    #                     method='compute',
    #                     timewindow=timestrs,
    #                     catalog=[self._paths[i]['catalog'] for i in
    #                              timestrs],
    #                     model=model_j,
    #                     ref_model=self.get_model(test_k.ref_model),
    #                     path=self._paths[timestrs[-1]][
    #                         'evaluations'][test_k.name][model_j.name]
    #                 )
    #                 tasks.append(task_k)
    #     elif 'Discrete' in test_k.type and 'Batch' in test_k.type:
    #         timestr = timewindow2str(self.timewindows[-1])
    #         for model_j in self.models:
    #             task_k = Task(
    #                 instance=test_k,
    #                 method='compute',
    #                 timewindow=timestr,
    #                 catalog=self._paths[timestr]['catalog'],
    #                 ref_model=self.models,
    #                 model=model_j,
    #                 path=self._paths[timestr][
    #                     'evaluations'][test_k.name][model_j.name]
    #             )
    #             tasks.append(task_k)
    #
    # self.tasks = tasks

    def prepare_tasks(self) -> None:
        """
        Implements the Experiment's run logic, as depth-search.
        """
        '''
        Time-Window 
            Catalog Preparation >
                Forecast Creation >
                    Individual Tests |
                Comparative Tests |
        Sequential Tests |
        '''

        tasks = []

        for time_i in self.timewindows:
            time_str = timewindow2str(time_i)
            task_i = Task(instance=self, method='prepare_subcatalog',
                          tstring=time_str)
            tasks.append(task_i)
            # Consistency Tests
            for model_j in self.models:
                task_ij = Task(instance=model_j, method='create_forecast',
                               tstring=time_str)
                tasks.append(task_ij)

                for test_k in self.tests:
                    if 'Discrete' in test_k.type and 'Absolute' in test_k.type:
                        task_ijk = Task(
                            instance=test_k,
                            method='compute',
                            timewindow=time_str,
                            catalog=self._paths[time_str]['catalog'],
                            model=model_j,
                            path=self._paths[time_str][
                                'evaluations'][test_k.name][model_j.name]
                        )
                        tasks.append(task_ijk)

            # Comparative Tests
            for test_k in self.tests:
                if 'Discrete' in test_k.type and 'Comparative' in test_k.type:
                    for model_j in self.models:
                        task_ik = Task(
                            instance=test_k,
                            method='compute',
                            timewindow=time_str,
                            catalog=self._paths[time_str]['catalog'],
                            model=model_j,
                            ref_model=self.get_model(test_k.ref_model),
                            path=self._paths[time_str][
                                'evaluations'][test_k.name][model_j.name]
                        )
                        tasks.append(task_ik)
        for test_k in self.tests:
            if 'Sequential' in test_k.type:
                if 'Absolute' in test_k.type:
                    timestrs = timewindow2str(self.timewindows)
                    for model_j in self.models:
                        task_k = Task(
                            instance=test_k,
                            method='compute',
                            timewindow=timestrs,
                            catalog=[self._paths[i]['catalog'] for i in
                                     timestrs],
                            model=model_j,
                            path=self._paths[timestrs[-1]][
                                'evaluations'][test_k.name][model_j.name]
                        )
                        tasks.append(task_k)
                elif 'Comparative' in test_k.type:
                    timestrs = timewindow2str(self.timewindows)
                    for model_j in self.models:
                        task_k = Task(
                            instance=test_k,
                            method='compute',
                            timewindow=timestrs,
                            catalog=[self._paths[i]['catalog'] for i in
                                     timestrs],
                            model=model_j,
                            ref_model=self.get_model(test_k.ref_model),
                            path=self._paths[timestrs[-1]][
                                'evaluations'][test_k.name][model_j.name]
                        )
                        tasks.append(task_k)
            elif 'Discrete' in test_k.type and 'Batch' in test_k.type:
                timestr = timewindow2str(self.timewindows[-1])
                for model_j in self.models:
                    task_k = Task(
                        instance=test_k,
                        method='compute',
                        timewindow=timestr,
                        catalog=self._paths[timestr]['catalog'],
                        ref_model=self.models,
                        model=model_j,
                        path=self._paths[timestr][
                            'evaluations'][test_k.name][model_j.name]
                    )
                    tasks.append(task_k)

        self.tasks = tasks

    def get_model(self, name: str) -> Model:
        for model in self.models:
            if model.name == name:
                return model

    @property
    def catalog(self) -> CSEPCatalog:

        if callable(self._catalog):
            if os.path.isfile(self._catpath):
                return CSEPCatalog.load_json(self._catpath)
            bounds = {'start_time': min([item for sublist in self.timewindows
                                         for item in sublist]),
                      'end_time': max([item for sublist in self.timewindows
                                       for item in sublist]),
                      'min_magnitude': self.magnitudes.min(),
                      'max_depth': self.depths.max()}
            if self.region:
                bounds.update({i: j for i, j in
                               zip(['min_longitude', 'max_longitude',
                                    'min_latitude', 'max_latitude'],
                                   self.region.get_bbox())})

            catalog = self._catalog(
                catalog_id='cat',  # todo name as run
                verbose=True,
                **bounds
            )

            if self.region:
                catalog.filter_spatial(region=self.region)
                catalog.region = None
            catalog.write_json(self._catpath)

            return catalog

        elif os.path.isfile(self._catalog):
            return CSEPCatalog.load_json(self._catpath)

    @catalog.setter
    def catalog(self, cat: Union[Callable, CSEPCatalog, str]) -> None:

        if os.path.isfile(self._abspath(cat)[1]):
            print(f"Using catalog from {cat}")
            self._catalog = self._abspath(cat)[1]
            self._catpath = self._abspath(cat)[1]

        else:
            # catalog can be a function
            self._catalog = parse_csep_func(cat)
            self._catpath = self._abspath('catalog.json')[1]
            if os.path.isfile(self._catpath):
                print(f"Using stored catalog "
                      f"'{os.path.relpath(self._catpath, self.path)}', "
                      f"obtained from function '{cat}'")
            else:
                print(f"Downloading catalog from function {cat}")

    def run(self) -> None:
        """
        Run the task tree

        todo:
         - Cleanup forecast (perhaps add a clean task in self.prepare_tasks,
            after all test had been run for a given forecast)
         - Task dependence graph
         - Memory monitor?
         - Queuer?

        """

        for task in self.tasks:
            task.run()

    def _read_results(self, test: Evaluation, window: str) -> List:

        test_results = []
        if not isinstance(window, str):
            wstr_ = timewindow2str(window)
        else:
            wstr_ = window

        if 'T' in test.name:  # todo cleaner
            models = [i for i in self.models if i.name != test.ref_model]
        else:
            models = self.models
        for i in models:
            eval_path = self._paths[wstr_]['evaluations'][test.name][i.name]
            with open(eval_path, 'r') as file_:
                model_eval = EvaluationResult.from_dict(json.load(file_))
            test_results.append(model_eval)
        return test_results

    def plot_results(self, dpi: int = 300, show: bool = False) -> None:
        """
        
        Plots all evaluation results
 
        Args:
            dpi: Figure resolution with which to save
            show: show in runtime

        """

        for time in self.timewindows:
            timestr = timewindow2str(time)
            figpaths = self._paths[timestr]['figures']

            # consistency and comparative
            for test in self.tests:
                if 'Discrete' in test.type and 'Absolute' in test.type:
                    results = self._read_results(test, time)
                    ax = test.plot_func(results, plot_args=test.plot_args,
                                        **test.plot_kwargs)
                    if 'code' in test.plot_args:
                        exec(test.plot_args['code'])
                    pyplot.savefig(figpaths[test.name], dpi=dpi)
                    if show:
                        pyplot.show()

        for test in self.tests:

            timestr = timewindow2str(self.timewindows[-1])
            results = self._read_results(test, timestr)
            if test.type == 'seqcomp':
                results_ = []
                for i in results:
                    if i.sim_name != test.ref_model:
                        results_.append(i)
                results = results_
            if 'Sequential' in test.type:
                test.plot_args['timestrs'] = timewindow2str(self.timewindows)
            import matplotlib
            print(matplotlib.__version__)
            ax = test.plot_func(results, plot_args=test.plot_args,
                                **test.plot_kwargs)
            if 'code' in test.plot_args:
                exec(test.plot_args['code'])
            pyplot.savefig(figpaths[test.name], dpi=dpi)
            if show:
                pyplot.show()

    def plot_forecasts(self) -> None:
        """

        Plots and saves all the generated forecasts

        """

        plot_fc_config = self.postproc_config.get('plot_forecasts')
        if plot_fc_config:
            try:
                proj_ = plot_fc_config.get('projection')
                if isinstance(proj_, dict):
                    proj_name = list(proj_.keys())[0]
                    proj_args = list(proj_.values())[0]
                else:
                    proj_name = proj_
                    proj_args = {}
                plot_fc_config['projection'] = getattr(ccrs, proj_name)(
                    **proj_args)
            except (IndexError, KeyError):
                plot_fc_config['projection'] = ccrs.PlateCarree(
                    central_longitude=0.0)

            cat = plot_fc_config.get('catalog')
            cat_args = {}
            if cat:
                cat_args = {'markersize': 7, 'markercolor': 'black',
                            'title': None,
                            'legend': False, 'basemap': None,
                            'region_border': False}
                if self.region:
                    self.catalog.filter_spatial(self.region, in_place=True)
                if isinstance(cat, dict):
                    cat_args.update(cat)

            window = self.timewindows[-1]
            winstr = timewindow2str(window)
            for model in self.models:
                fig_path = self._paths[winstr]['models']['figures'][
                    model.name]
                start = decimal_year(window[0])
                end = decimal_year(window[1])
                time = f'{round(end - start, 3)} years'
                plot_args = {'region_border': False,
                             'cmap': 'magma',
                             'clabel': r'$\log_{10} N\left(M_w \in [{%.2f},'
                                       r'\,{%.2f}]\right)$ per '
                                       r'$0.1^\circ\times 0.1^\circ $ per %s' %
                                       (self.magnitudes.min(),
                                        self.magnitudes.max(), time)}
                if not self.region or self.region.name == 'global':
                    set_global = True
                else:
                    set_global = False
                plot_args.update(plot_fc_config)
                ax = model.forecasts[winstr].plot(
                    set_global=set_global, plot_args=plot_args)

                if self.region:
                    bbox = self.region.get_bbox()
                    dh = self.region.dh
                    extent = [bbox[0] - 3 * dh, bbox[1] + 3 * dh,
                              bbox[2] - 3 * dh, bbox[3] + 3 * dh]
                else:
                    extent = None
                if cat:
                    self.catalog.plot(ax=ax, set_global=set_global,
                                      extent=extent, plot_args=cat_args)

                pyplot.savefig(fig_path, dpi=300, facecolor=(0, 0, 0, 0))

    def generate_report(self) -> None:
        """

        Creates a report summarizing the Experiment's results

        """

        report.generate_report(self)

    def to_dict(self, exclude: Sequence = ('magnitudes', 'depths',
                                           'timewindows', 'reg'),
                extended: bool = False) -> dict:
        """
        Converts an Experiment instance into a dictionary.

        Args:
            exclude (tuple, list): Attributes, or attribute keys, to ignore
            extended (bool): Verbose representation of pycsep objects
            (e.g. region)

        Returns:
            A dictionary with serialized instance's attributes, which are
            feCSEP readable
        """

        def _get_value(x):
            # For each element type, transforms to desired string/output
            if hasattr(x, 'to_dict') and extended:
                # e.g. csep region, model, test, etc.
                o = x.to_dict()
            else:
                try:
                    try:
                        o = getattr(x, '__name__')
                    except AttributeError:
                        o = getattr(x, 'name')
                except AttributeError:
                    if isinstance(x, numpy.ndarray):
                        o = x.tolist()
                    else:
                        o = x
            return o

        def iter_attr(val):
            # recursive iter through nested dicts/lists
            if isinstance(val, Mapping):
                return {item: iter_attr(val_) for item, val_ in val.items()
                        if ((item not in exclude) and val_) or extended}
            elif isinstance(val, Sequence) and not isinstance(val, str):
                return [iter_attr(i) for i in val]
            else:
                return _get_value(val)

        dictwalk = {i: j for i, j in self.__dict__.items() if
                    not i.startswith('_')}
        dictwalk.update({'catalog': self._catpath})

        return iter_attr(dictwalk)

    def to_yml(self, filename: str, **kwargs) -> None:
        """

        Serializes the :class:`~fecsep.experiment.Experiment` instance into a
        .yml file.

        Note:
            This instance can then be reinstantiated using
            :meth:`~fecsep.experiment.Experiment.from_yml`

        Args:
            filename: Name of the file onto which dump the instance
            **kwargs: Passed to :meth:`~fecsep.experiment.Experiment.to_dict`

        Returns:

        """

        class NoAliasDumper(yaml.Dumper):
            def ignore_aliases(self, data):
                return True

        with open(filename, 'w') as f_:
            yaml.dump(
                self.to_dict(**kwargs), f_,
                Dumper=NoAliasDumper,
                sort_keys=False,
                default_flow_style=False,
                indent=1,
                width=70
            )

    @classmethod
    def from_yml(cls, config_yml: str):
        """

        Initializes an experiment from a .yml file. It must contain the
        attributes described in the :class:`~fecsep.experiment.Experiment`,
        :func:`~fecsep.utils.read_time_config` and
        :func:`~fecsep.utils.read_region_config` descriptions

        Args:
            config_yml (str): The path to the .yml file

        Returns:
            An :class:`~fecsep.experiment.Experiment` class instance

        """
        with open(config_yml, 'r') as yml:
            config_dict = yaml.safe_load(yml)
            if 'path' not in config_dict:
                config_dict['path'] = os.path.abspath(
                    os.path.dirname(config_yml))
        return cls(**config_dict)
