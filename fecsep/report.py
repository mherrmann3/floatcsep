from fecsep.utils import MarkdownReport, timewindow_str
import os

"""
Use the MarkdownReport class to create output for the gefe_qtree

1. string templates are stored for each evaluation
2. string templates are stored for each forecast
3. report should include
    - plots of catalog
    - plots of forecasts
    - evaluation results
    - metadata from run, (maybe json dump of gefe_qtree class)
"""


def generate_report(experiment, timewindow=-1):
    if isinstance(timewindow, int):
        timewindow = experiment.time_windows[timewindow]
        timestr = timewindow_str(timewindow)
    elif isinstance(timewindow, (list, tuple)):
        timestr = timewindow_str(timewindow)
    else:
        timestr = timewindow
        timewindow = [i for i in experiment.time_windows if
                      timewindow(i) == timestr][0]

    report = MarkdownReport()
    report.add_title(
        f"Testing report {experiment.name}", ''
    )
    report.add_heading("Objectives", level=2)
    objs = [
        "Describe the predictive skills of posited hypothesis about seismogenesis with earthquakes of "
        "M5.95+ independent observations around the globe.",
        "Identify the methods and geophysical datasets that lead to the highest information gains in "
        "global earthquake forecasting.",
        "Test earthquake forecast models on different grid settings.",
        "Use Quadtree based grid to represent and evaluate earthquake forecasts."
    ]
    report.add_list(objs)
    # Generate plot of the catalog

    # if experiment.catalog is not None:
    #     cat_path = experiment._paths[timestr]['catalog']
    #     figure_path = os.path.splitext(cat_path)[0]
    #     # relative to top-level directory
    #     if experiment.region:
    #         experiment.catalog.filter_spatial(experiment.region, in_place=True)
    #     ax = experiment.catalog.plot(plot_args={
    #         'figsize': (12, 8),
    #         'markersize': 8,
    #         'markercolor': 'black',
    #         'grid_fontsize': 16,
    #         'title': '',
    #         'legend': False
    #     })
    #     ax.get_figure().tight_layout()
    #     ax.get_figure().savefig(f"{figure_path}.png")
    #     report.add_figure(
    #         f"ISC gCMT Authoritative Catalog",
    #         figure_path,
    #         level=2,
    #         caption="The authoritative evaluation data is the full Global CMT catalog (Ekström et al. 2012). "
    #                 "We confine the hypocentral depths of earthquakes in training and testing datasets to a "
    #                 f"maximum of 70km. The plot shows the catalog for the testing period which ranges from "
    #                 f"{timewindow[0]} until {timewindow[1]}. "  # todo
    #                 f"Earthquakes are filtered above Mw {experiment.magnitudes.min()}. "
    #                 "Black circles depict individual earthquakes with its radius proportional to the magnitude.",
    #         add_ext=True
    #     )
    report.add_heading(
        "Results",
        level=2,
        text="We apply the following tests to each of the forecasts considered in this gefe. "
             "More information regarding the tests can be found [here](https://docs.cseptesting.org/getting_started/theory.html)."
    )
    test_names = [test.name for test in experiment.tests]
    report.add_list(test_names)

    # Include results from Experiment
    for test in experiment.tests:
        fig_path = experiment._paths[timestr]['figures'][test.name]
        report.add_figure(
            f"{test.name}",
            fig_path,
            level=3,
            caption=test.markdown,
            add_ext=True
        )

    report.table_of_contents()
    report.save(experiment.run_folder)
