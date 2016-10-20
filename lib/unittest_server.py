import os
import re
import sys
import glob
import traceback
import subprocess
from subprocess import Popen, PIPE, STDOUT

from lib.server import Server
from lib.tarantool_server import Test

class UnitTest(Test):
    def execute(self, server):
        execs = [os.path.join(server.builddir, "test", self.name)]
        proc = Popen(execs, stdout=PIPE, stderr=STDOUT)
        sys.stdout.write(proc.communicate()[0])

class UnittestServer(Server):
    def __init__(self, _ini=None):
        if _ini is None:
            _ini = {}
        ini = {
            'vardir': None,
        }; ini.update(_ini)
        Server.__init__(self, ini)
        self.vardir = ini['vardir']
        self.builddir = ini['builddir']
        self.debug = False

    def deploy(self, vardir=None, silent=True, wait=True):
        self.vardir = vardir
        if not os.access(self.vardir, os.F_OK):
            os.makedirs(self.vardir)

    @classmethod
    def find_exe(cls, builddir):
        cls.builddir = builddir

    def find_tests(self, test_suite, suite_path):
        def patterned(test, patterns):
            answer = []
            for i in patterns:
                if test.name.find(i) != -1:
                    answer.append(test)
            return answer

        test_suite.ini['suite'] = suite_path
        tests = glob.glob(os.path.join(suite_path, "*.test" ))

        if not tests:
            tests = glob.glob(os.path.join(self.builddir, 'test', suite_path, '*.test'))
        test_suite.tests = [UnitTest(k, test_suite.args, test_suite.ini) for k in sorted(tests)]
        test_suite.tests = sum([patterned(x, test_suite.args.tests) for x in test_suite.tests], [])

    def print_log(self, lines):
        pass
