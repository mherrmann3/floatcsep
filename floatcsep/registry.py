import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from os.path import join, abspath, relpath, normpath, dirname, exists
from typing import Sequence, Union, TYPE_CHECKING, Any

from floatcsep.utils import timewindow2str

if TYPE_CHECKING:
    from floatcsep.model import Model
    from floatcsep.evaluation import Evaluation

log = logging.getLogger("floatLogger")


class BaseFileRegistry(ABC):

    def __init__(self, workdir: str) -> None:
        self.workdir = workdir

    @staticmethod
    def _parse_arg(arg) -> Union[str, list[str]]:
        if isinstance(arg, (list, tuple)):
            return timewindow2str(arg)
        elif isinstance(arg, str):
            return arg
        elif hasattr(arg, "name"):
            return arg.name
        elif hasattr(arg, "__name__"):
            return arg.__name__
        else:
            raise Exception("Arg is not found")

    @abstractmethod
    def as_dict(self) -> dict:
        pass

    @abstractmethod
    def build_tree(self, *args, **kwargs) -> None:
        pass

    @abstractmethod
    def get(self, *args: Sequence[str]) -> Any:
        pass

    def abs(self, *paths: Sequence[str]) -> str:
        _path = normpath(abspath(join(self.workdir, *paths)))
        return _path

    def abs_dir(self, *paths: Sequence[str]) -> str:
        _path = normpath(abspath(join(self.workdir, *paths)))
        _dir = dirname(_path)
        return _dir

    def rel(self, *paths: Sequence[str]) -> str:
        """Gets the relative path of a file, when it was defined relative to.

        the experiment working dir.
        """

        _abspath = normpath(abspath(join(self.workdir, *paths)))
        _relpath = relpath(_abspath, self.workdir)
        return _relpath

    def rel_dir(self, *paths: Sequence[str]) -> str:
        """Gets the absolute path of a file, when it was defined relative to.

        the experiment working dir.
        """

        _path = normpath(abspath(join(self.workdir, *paths)))
        _dir = dirname(_path)

        return relpath(_dir, self.workdir)

    def file_exists(self, *args: Sequence[str]):
        file_abspath = self.get(*args)
        return exists(file_abspath)


class ForecastRegistry(BaseFileRegistry):
    def __init__(
        self,
        workdir: str,
        path: str,
        database: str = None,
        args_file: str = None,
        input_cat: str = None,
    ) -> None:
        super().__init__(workdir)

        self.path = path
        self.database = database
        self.args_file = args_file
        self.input_cat = input_cat
        self.forecasts = {}

    def get(self, *args: Sequence[str]):
        val = self.__dict__
        for i in args:
            parsed_arg = self._parse_arg(i)
            val = val[parsed_arg]
        return self.abs(val)

    def get_forecast(self, *args: Sequence[str]) -> str:

        return self.get("forecasts", *args)

    @property
    def dir(self) -> str:
        """
        Returns:

            The directory containing the model source.
        """
        if os.path.isdir(self.get("path")):
            return self.get("path")
        else:
            return os.path.dirname(self.get("path"))

    @property
    def fmt(self) -> str:
        if self.database:
            return os.path.splitext(self.database)[1][1:]
        else:
            return os.path.splitext(self.path)[1][1:]

    def as_dict(self) -> dict:
        return {
            "workdir": self.workdir,
            "path": self.path,
            "database": self.database,
            "args_file": self.args_file,
            "input_cat": self.input_cat,
            "forecasts": self.forecasts,
        }

    def forecast_exists(self, timewindow: Union[str, list]) -> Union[bool, Sequence[bool]]:

        if isinstance(timewindow, str):
            return self.file_exists("forecasts", timewindow)
        else:
            return [self.file_exists("forecasts", i) for i in timewindow]

    def build_tree(
        self,
        timewindows: Sequence[Sequence[datetime]] = None,
        model_class: str = "TimeIndependentModel",
        prefix: str = None,
        args_file: str = None,
        input_cat: str = None,
    ) -> None:
        """
        Creates the run directory, and reads the file structure inside.

        Args:
            timewindows (list(str)): List of time windows or strings.
            model_class (str): Model's class name
            prefix (str): prefix of the model forecast filenames if TD
            args_file (str, bool): input arguments path of the model if TD
            input_cat (str, bool): input catalog path of the model if TD

        Returns:
            run_folder: Path to the run.
             exists: flag if forecasts, catalogs and test_results if they
             exist already
             target_paths: flag to each element of the gefe (catalog and
             evaluation results)
        """

        windows = timewindow2str(timewindows)

        if model_class == "TimeIndependentModel":
            fname = self.database if self.database else self.path
            self.forecasts = {win: fname for win in windows}

        elif model_class == "TimeDependentModel":

            args = args_file if args_file else join("input", "args.txt")
            self.args_file = join(self.path, args)
            input_cat = input_cat if input_cat else join("input", "catalog.csv")
            self.input_cat = join(self.path, input_cat)
            # grab names for creating directories
            subfolders = ["input", "forecasts"]
            dirtree = {folder: self.abs(self.path, folder) for folder in subfolders}

            # create directories if they don't exist
            for _, folder_ in dirtree.items():
                os.makedirs(folder_, exist_ok=True)

            # set forecast names
            self.forecasts = {
                win: join(dirtree["forecasts"], f"{prefix}_{win}.csv") for win in windows
            }

    def log_tree(self) -> None:
        """
        Logs a grouped summary of the forecasts' dictionary.
        Groups time windows by whether the forecast exists or not.
        """
        exists_group = []
        not_exist_group = []

        for timewindow, filepath in self.forecasts.items():
            if self.forecast_exists(timewindow):
                exists_group.append(timewindow)
            else:
                not_exist_group.append(timewindow)

        log.debug(f"    Existing forecasts: {len(exists_group)}")
        log.debug(f"    Missing forecasts: {len(not_exist_group)}")
        for timewindow in not_exist_group:
            log.debug(f"      Time Window: {timewindow}")


class ExperimentRegistry(BaseFileRegistry):
    def __init__(self, workdir: str, run_dir: str = "results") -> None:
        super().__init__(workdir)
        self.run_dir = run_dir
        self.results = {}
        self.test_catalogs = {}
        self.figures = {}

        self.repr_config = "repr_config.yml"
        self.forecast_registries = {}

    def add_forecast_registry(self, model: "Model") -> None:
        """
        Adds a model's ForecastRegistry to the ExperimentRegistry.

        Args:
            model (str): A Model object

        """
        self.forecast_registries[model.name] = model.registry

    def get_forecast_registry(self, model_name: str) -> None:
        """
        Retrieves a model's ForecastRegistry from the ExperimentRegistry.

        Args:
            model_name (str): The name of the model.

        Returns:
            ForecastRegistry: The ForecastRegistry associated with the model.
        """
        return self.forecast_registries.get(model_name)

    def log_forecast_trees(self, timewindows: list) -> None:
        """
        Logs the forecasts for all models managed by this ExperimentRegistry.
        """
        log.debug("===================")
        log.debug(f" Total Time Windows: {len(timewindows)}")
        for model_name, registry in self.forecast_registries.items():
            log.debug(f"  Model: {model_name}")
            registry.log_tree()
        log.debug("===================")

    def get(self, *args: Sequence[any]) -> str:
        val = self.__dict__
        for i in args:
            parsed_arg = self._parse_arg(i)
            val = val[parsed_arg]
        return self.abs(self.run_dir, val)

    def get_result(self, *args: Sequence[any]) -> str:
        val = self.results
        for i in args:
            parsed_arg = self._parse_arg(i)
            val = val[parsed_arg]
        return self.abs(self.run_dir, val)

    def get_test_catalog(self, *args: Sequence[any]) -> str:
        val = self.test_catalogs
        for i in args:
            parsed_arg = self._parse_arg(i)
            val = val[parsed_arg]
        return self.abs(self.run_dir, val)

    def get_figure(self, *args: Sequence[any]) -> str:
        val = self.figures
        for i in args:
            parsed_arg = self._parse_arg(i)
            val = val[parsed_arg]
        return self.abs(self.run_dir, val)

    def result_exist(self, timewindow_str: str, test_name: str, model_name: str) -> bool:

        return self.file_exists("results", timewindow_str, test_name, model_name)

    def as_dict(self) -> str:
        # todo: rework
        return self.workdir

    def build_tree(
        self,
        timewindows: Sequence[Sequence[datetime]],
        models: Sequence["Model"],
        tests: Sequence["Evaluation"],
    ) -> None:
        """
        Creates the run directory, and reads the file structure inside.

        Args:
            timewindows: List of time windows, or representing string.
            models: List of models or model names
            tests: List of tests or test names

        Returns:
            run_folder: Path to the run.
             exists: flag if forecasts, catalogs and test_results if they
             exist already
             target_paths: flag to each element of the experiment (catalog and
             evaluation results)
        """
        windows = timewindow2str(timewindows)

        models = [i.name for i in models]
        tests = [i.name for i in tests]

        run_folder = self.run_dir
        subfolders = ["catalog", "evaluations", "figures"]
        dirtree = {
            win: {folder: self.abs(run_folder, win, folder) for folder in subfolders}
            for win in windows
        }

        # create directories if they don't exist
        for tw, tw_folder in dirtree.items():
            for _, folder_ in tw_folder.items():
                os.makedirs(folder_, exist_ok=True)

        results = {
            win: {
                test: {
                    model: join(win, "evaluations", f"{test}_{model}.json") for model in models
                }
                for test in tests
            }
            for win in windows
        }
        test_catalogs = {win: join(win, "catalog", "test_catalog.json") for win in windows}

        figures = {
            "main_catalog_map": "catalog",
            "main_catalog_time": "events",
            **{
                win: {
                    **{test: join(win, "figures", f"{test}") for test in tests},
                    "catalog": join(win, "figures", "catalog_map"),
                    "magnitude_time": join(win, "figures", "catalog_time"),
                    "forecasts": {
                        model: join(win, "figures", f"forecast_{model}") for model in models
                    },
                }
                for win in windows
            },
        }

        self.results = results
        self.test_catalogs = test_catalogs
        self.figures = figures

    def log_results_tree(self):
        """
        Logs a summary of the results dictionary, sorted by test.
        For each test and time window, it logs whether all models have results,
        or if some results are missing, and specifies which models are missing.
        """
        log.debug("===================")

        total_results = results_exist_count = results_not_exist_count = 0

        # Get all unique test names and sort them
        all_tests = sorted(
            {test_name for tests in self.results.values() for test_name in tests}
        )

        for test_name in all_tests:
            log.debug(f"Test: {test_name}")
            for timewindow, tests in self.results.items():
                if test_name in tests:
                    models = tests[test_name]
                    missing_models = []

                    for model_name, result_path in models.items():
                        total_results += 1
                        result_full_path = self.get_result(timewindow, test_name, model_name)
                        if os.path.exists(result_full_path):
                            results_exist_count += 1
                        else:
                            results_not_exist_count += 1
                            missing_models.append(model_name)

                    if not missing_models:
                        log.debug(f"  Time Window: {timewindow} - All models evaluated.")
                    else:
                        log.debug(
                            f"  Time Window: {timewindow} - Missing results for models: {', '.join(missing_models)}"
                        )

        log.debug(f"Total Results: {total_results}")
        log.debug(f"Results that Exist: {results_exist_count}")
        log.debug(f"Results that Do Not Exist: {results_not_exist_count}")
        log.debug("===================")
