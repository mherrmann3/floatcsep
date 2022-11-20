import os.path
import tempfile
from unittest import TestCase
from datetime import datetime
from fecsep.core import Experiment
import numpy


class TestExperiment(TestCase):

    def assertEqualExperiment(self, exp_a, exp_b):
        self.assertEqual(exp_a.name, exp_b.name)
        self.assertEqual(exp_a.path, os.getcwd())
        self.assertEqual(exp_a.path, exp_b.path)
        self.assertEqual(exp_a.start_date, exp_b.start_date)
        self.assertEqual(exp_a.time_windows, exp_b.time_windows)
        self.assertEqual(exp_a.exp_class, exp_b.exp_class)
        self.assertEqual(exp_a.region, exp_b.region)
        numpy.testing.assert_equal(exp_a.magnitudes, exp_b.magnitudes)
        numpy.testing.assert_equal(exp_a.depths, exp_b.depths)
        self.assertEqual(exp_a.catalog_reader, exp_b.catalog_reader)

    def test_init(self):
        _region = os.path.join(os.path.dirname(__file__),
                               'artifacts', 'regions', 'mock_region')
        time_config = {'start_date': datetime(2021, 1, 1),
                       'end_date': datetime(2022, 1, 1)}
        region_config = {'region': _region,
                         'mag_max': 1.2,
                         'mag_min': 1.0,
                         'mag_bin': 0.1,
                         'depth_min': 0,
                         'depth_max': 1}

        exp_a = Experiment(**time_config, **region_config,
                           catalog_reader='query_comcat')
        exp_b = Experiment(time_config=time_config,
                           region_config=region_config,
                           catalog_reader='query_comcat')
        self.assertEqualExperiment(exp_a, exp_b)

    def test_to_dict(self):
        time_config = {'start_date': datetime(2020, 1, 1),
                       'end_date': datetime(2021, 1, 1),
                       'horizon': '6 month',
                       'growth': 'cumulative'}

        region_config = {'region': 'california_relm_region',
                         'mag_max': 9.0,
                         'mag_min': 3.0,
                         'mag_bin': 0.1,
                         'depth_min': -2,
                         'depth_max': 70}

        exp_a = Experiment(**time_config, **region_config,
                           catalog_reader='query_comcat')

        dict_ = {'name': None,
                 'path': os.getcwd(),
                 'time_config':
                     {'exp_class': 'ti',
                      'start_date': datetime(2020, 1, 1).isoformat(),
                      'end_date': datetime(2021, 1, 1).isoformat(),
                      'horizon': '6-months',
                      'growth': 'cumulative',
                      'time_windows':
                          [[datetime(2020, 1, 1).isoformat(),
                            datetime(2020, 7, 1).isoformat()],
                           [datetime(2020, 1, 1).isoformat(),
                            datetime(2021, 1, 1).isoformat()]]},
                 'region_config': {
                     'region': 'california_relm_region',
                     'mag_max': 9.0,
                     'mag_min': 3.0,
                     'mag_bin': 0.1,
                     'depth_min': -2,
                     'depth_max': 70
                 },
                 'catalog': None,
                 'catalog_reader': 'query_comcat',
                 'model_config': None,
                 'test_config': None,
                 'postproc_config': {},
                 'default_test_kwargs': None,
                 'models': [],
                 'tests': [],
                 'run_results': {},
                 'run_folder': '',
                 'target_paths': {},
                 'exists': {}}

        self.assertEqual(dict_, exp_a.to_dict())

    def test_to_yml(self):
        time_config = {'start_date': datetime(2021, 1, 1),
                       'end_date': datetime(2022, 1, 1),
                       'intervals': 12}

        region_config = {'region': 'california_relm_region',
                         'mag_max': 9.0,
                         'mag_min': 3.0,
                         'mag_bin': 0.1,
                         'depth_min': -2,
                         'depth_max': 70}

        exp_a = Experiment(**time_config, **region_config,
                           catalog_reader='query_comcat')

        file_ = tempfile.mkstemp()[1]
        exp_a.to_yml(file_)
        exp_b = Experiment.from_yml(file_)
        self.assertEqualExperiment(exp_a, exp_b)

        file_ = tempfile.mkstemp()[1]
        exp_a.to_yml(file_, extended=True)
        exp_c = Experiment.from_yml(file_)
        self.assertEqualExperiment(exp_a, exp_c)
