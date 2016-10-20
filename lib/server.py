import glob
import os
import shutil


class Server(object):
    """Server represents a single server instance. Normally, the
    program operates with only one server, but in future we may add
    replication slaves. The server is started once at the beginning
    of each suite, and stopped at the end."""
    DEFAULT_INSPECTOR = 0

    @property
    def vardir(self):
        if not hasattr(self, '_vardir'):
            raise ValueError("No vardir specified")
        return self._vardir
    @vardir.setter
    def vardir(self, path):
        if path == None:
            return
        self._vardir = os.path.abspath(path)

    def __init__(self, ini):
        self.core = ini['core']
        self.ini = ini
        self.re_vardir_cleanup = ['*.core.*', 'core']
        self.vardir = ini['vardir']
        self.inspector_port = int(ini.get(
            'inspector_port', self.DEFAULT_INSPECTOR
        ))

    def prepare_args(self):
        return []

    def cleanup(self, full=False):
        if full:
            shutil.rmtree(self.vardir)
            return
        for re in self.re_vardir_cleanup:
            for f in glob.glob(os.path.join(self.vardir, re)):
                if os.path.isdir(f):
                    shutil.rmtree(f)
                else:
                    os.remove(f)

    def install(self, binary=None, vardir=None, mem=None, silent=True):
        pass
    def init(self):
        pass
    def start(self, silent=True):
        pass
    def stop(self, silent=True):
        pass
    def restart(self):
        pass
