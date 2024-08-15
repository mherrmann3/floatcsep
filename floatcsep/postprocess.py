import importlib.util
import logging
import os
from datetime import datetime
from typing import TYPE_CHECKING, Union

from cartopy import crs as ccrs
from matplotlib import pyplot

from floatcsep.utils import (
    timewindow2str,
    magnitude_vs_time,
)

if TYPE_CHECKING:
    from floatcsep.experiment import Experiment

log = logging.getLogger("floatLogger")


def plot_results(experiment: "Experiment") -> None:
    """Plots all evaluation results."""
    log.info("Plotting evaluation results")
    timewindows = timewindow2str(experiment.timewindows)

    for test in experiment.tests:
        test.plot_results(timewindows, experiment.models, experiment.registry)


def plot_forecasts(experiment: "Experiment") -> None:
    """Plots and saves all the generated forecasts."""

    # Parsing plot configuration file
    plot_forecast_config: dict = parse_plot_config(
        experiment.postprocess.get("plot_forecasts", {})
    )
    if not isinstance(plot_forecast_config, dict):
        return

    #####################################
    # Default forecast plotting function.
    #####################################
    log.info("Plotting forecasts")

    # Get the time windows to be plotted. Defaults to only the last time window.
    time_windows: list[list[datetime]] = (
        timewindow2str(experiment.timewindows)
        if plot_forecast_config.get("all_time_windows")
        else [timewindow2str(experiment.timewindows[-1])]
    )

    # Get the projection of the plots
    plot_forecast_config["projection"]: ccrs.Projection = parse_projection(
        plot_forecast_config.get("projection")
    )

    for model in experiment.models:
        for window in time_windows:
            ax = model.get_forecast(window, experiment.region).plot(
                plot_args=plot_forecast_config
            )

            # If catalog option is passed, catalog is plotted on top of the forecast
            if plot_forecast_config.get("catalog"):
                cat_args = plot_forecast_config.get("catalog", {})
                experiment.catalog_repo.get_test_cat(window).plot(
                    ax=ax,
                    extent=ax.get_extent(),
                    plot_args=cat_args.update(
                        {
                            "basemap": plot_forecast_config.get("basemap", None),
                            "title": ax.get_title(),
                        }
                    ),
                )
            fig_path = experiment.registry.get_figure(window, "forecasts", model.name)
            pyplot.savefig(fig_path, dpi=plot_forecast_config.get("dpi", 300))


def plot_catalogs(experiment: "Experiment") -> None:

    # Parsing plot configuration file
    plot_catalog_config: dict = parse_plot_config(
        experiment.postprocess.get("plot_catalog", {})
    )
    if not isinstance(plot_catalog_config, dict):
        return

    ####################################
    # Default catalog plotting function.
    ####################################
    log.info("Plotting catalogs")

    # Get the projection of the plots
    plot_catalog_config["projection"]: ccrs.Projection = parse_projection(
        plot_catalog_config.get("projection")
    )
    # Get the start and end dates of the experiment (as a string)
    experiment_timewindow = timewindow2str([experiment.start_date, experiment.end_date])

    # Get the catalog for the entire duration of the experiment
    main_catalog = experiment.catalog_repo.get_test_cat(experiment_timewindow)

    # Skip plotting if no events
    if main_catalog.get_number_of_events() == 0:
        log.debug(f"Catalog has zero events in {experiment_timewindow}")
        return

    # Plot catalog map
    ax = main_catalog.plot(plot_args=plot_catalog_config)
    cat_map_path = experiment.registry.get_figure("main_catalog_map")
    ax.get_figure().savefig(cat_map_path, dpi=plot_catalog_config.get("dpi", 300))

    # Plot catalog time series vs. magnitude
    ax = magnitude_vs_time(main_catalog)
    cat_time_path = experiment.registry.get_figure("main_catalog_time")
    ax.get_figure().savefig(cat_time_path, dpi=plot_catalog_config.get("dpi", 300))

    # If selected, plot the test catalogs for each of the time windows
    if plot_catalog_config.get("all_time_windows"):
        for tw in experiment.timewindows:
            test_catalog = experiment.catalog_repo.get_test_cat(timewindow2str(tw))

            if test_catalog.get_number_of_events() != 0:
                log.debug(f"Catalog has zero events in {tw}. Skip plotting")
                continue

            ax = test_catalog.plot(plot_args=plot_catalog_config)
            cat_map_path = experiment.registry.get_figure(tw, "catalog_map")
            ax.get_figure().savefig(cat_map_path, dpi=plot_catalog_config.get("dpi", 300))

            ax = magnitude_vs_time(test_catalog)
            cat_time_path = experiment.registry.get_figure(tw, "catalog_time")
            ax.get_figure().savefig(cat_time_path, dpi=plot_catalog_config.get("dpi", 300))


def plot_custom(experiment: "Experiment"):

    plot_config = parse_plot_config(experiment.postprocess.get("plot_custom", None))
    if plot_config is None:
        return
    script_path, func_name = plot_config

    log.info(f"Plotting from script {script_path} and function {func_name}")
    script_abs_path = experiment.registry.abs(script_path)
    allowed_directory = os.path.dirname(experiment.registry.abs(experiment.config_file))

    if not os.path.isfile(script_path) or (
        os.path.dirname(script_abs_path) != os.path.realpath(allowed_directory)
    ):

        log.error(f"Script {script_path} is not in the configuration file directory.")
        log.info(
            "\t Skipping plotting. Script can be reallocated and re-run the plotting only"
            " by typing 'floatcsep run {config}'"
        )
        return

    module_name = os.path.splitext(os.path.basename(script_abs_path))[0]
    spec = importlib.util.spec_from_file_location(module_name, script_abs_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Execute the script securely
    try:
        func = getattr(module, func_name)

    except AttributeError:
        log.error(f"Function {func_name} not found in {script_path}")
        log.info(
            "\t Skipping plotting. Plot script can be modified and re-run the plotting only"
            " by typing 'floatcsep run {config}'"
        )
        return

    try:
        func(experiment)
    except Exception as e:
        log.error(f"Error executing {func_name} from {script_path}: {e}")
        log.info(
            "\t Skipping plotting. Plot script can be modified and re-run the plotting only"
            " by typing 'floatcsep run {config}'"
        )
    return


def parse_plot_config(plot_config: Union[dict, str, bool]):

    if plot_config is True:
        return {}

    elif plot_config in (None, False):
        return

    elif isinstance(plot_config, dict):
        return plot_config

    elif isinstance(plot_config, str):
        # Parse the script path and function name
        try:
            script_path, func_name = plot_config.split(".py:")
            script_path += ".py"
            return script_path, func_name
        except ValueError:
            log.error(
                f"Invalid format for custom plot function: {plot_config}. "
                "Try {script_name}.py:{func}"
            )
            log.info(
                "\t Skipping plotting. The script can be modified and re-run the plotting only "
                "by typing 'floatcsep run {config}'"
            )
            return

    else:
        log.error("Plot configuration not understood. Skipping plotting")
        return


def parse_projection(proj_config: Union[dict, str, bool]):
    """Retrieve projection configuration.
    e.g., as defined in the config file:
        projection:
            Mercator:
                central_longitude: 0.0
    """
    if proj_config is None:
        return ccrs.PlateCarree(central_longitude=0.0)

    if isinstance(proj_config, dict):
        proj_name, proj_args = next(iter(proj_config.items()))
    else:
        proj_name, proj_args = proj_config, {}

    if not isinstance(proj_name, str):
        return ccrs.PlateCarree(central_longitude=0.0)

    return getattr(ccrs, proj_name, ccrs.PlateCarree)(**proj_args)
