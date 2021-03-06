import os
import shlex
import sys
from ast import literal_eval
from collections import deque

import yaml
from gevent import socket

from lib.admin_connection import AdminAsyncConnection

class Namespace(object):
    pass

class LuaPreprocessorException(Exception):
    def __init__(self, val):
        super(LuaPreprocessorException, self).__init__()
        self.value = val
    def __str__(self):
        return "lua preprocessor error: " + repr(self.value)

class TestState(object):
    def __init__(self, suite_ini, default_server, create_server, params = {}):
        self.delimiter = ''
        self.suite_ini = suite_ini
        self.environ = Namespace()
        self.operation = False
        self.create_server = create_server
        self.servers = { 'default': default_server }
        self.connections = {}
        self.run_params = params
        if default_server is not None:
            self.connections =  { 'default': default_server.admin }
            # curcon is an array since we may have many connections
            self.curcon = [self.connections['default']]
            nmsp = Namespace()
            setattr(nmsp, 'admin', default_server.admin.uri)
            setattr(nmsp, 'listen', default_server.iproto.uri)
            setattr(self.environ, 'default', nmsp)

    def parse_preprocessor(self, string):
        token_store = deque()
        lexer = shlex.shlex(string)
        lexer.commenters = []
        token = lexer.get_token()
        if not token:
            return
        if token == 'setopt':
            option = lexer.get_token()
            if not option:
                raise LuaPreprocessorException("Wrong token for setopt: expected option name")
            value = lexer.get_token()
            if not value:
                raise LuaPreprocessorException("Wrong token for setopt: expected option value")
            return self.options(option, value)
        elif token == 'eval':
            name = lexer.get_token()
            expr = lexer.get_token()

            # token format: eval <server name> "<expr>"
            return self.lua_eval(name, expr[1:-1])
        elif token == 'wait_lsn':
            waiter = lexer.get_token()
            master = lexer.get_token()
            return self.wait_lsn(waiter, master)
        elif token == 'switch':
            server = lexer.get_token()
            return self.switch(server)
        elif token == 'config':
            var_name = lexer.get_token()
            return self.run_params
        token_store.append(token)
        token = lexer.get_token()
        if token == 'server':
            stype = token_store.popleft()
            sname = lexer.get_token()
            if not sname:
                raise LuaPreprocessorException("Wrong token for server: expected name")
            options = {}
            temp = lexer.get_token()
            if not temp:
                pass
            elif temp == 'with':
                while True:
                    k = lexer.get_token()
                    if not k:
                        break
                    v = lexer.get_token()
                    if v == '=':
                        v = lexer.get_token()
                    options[k] = v
                    lexer.get_token()
            else:
                raise LuaPreprocessorException("Wrong token for server: expected 'with', got " + repr(temp))
            return self.server(stype, sname, options)
        elif token == 'connection':
            ctype = token_store.popleft()
            cname = [lexer.get_token()]
            if not cname[0]:
                raise LuaPreprocessorException("Wrong token for connection: expected name")
            cargs = None
            temp = lexer.get_token()
            if temp == 'to':
                cargs = lexer.get_token()
            elif temp == ',':
                while True:
                    a = lexer.get_token()
                    if not a:
                        break
                    if a == ',':
                        continue
                    cname.append(a)
            elif temp:
                raise LuaPreprocessorException("Wrong token for server: expected 'to' or ',', got " + repr(temp))
            return self.connection(ctype, cname, cargs)
        elif token == 'filter':
            ftype = token_store.popleft()
            ref = None
            ret = None
            temp = lexer.get_token()
            if temp:
                ref = temp
                if not temp:
                    raise LuaPreprocessorException("Wrong token for filter: expected filter1")
                if lexer.get_token() != 'to':
                    raise LuaPreprocessorException("Wrong token for filter: expected 'to', got {0}".format(repr(temp)))
                temp = lexer.get_token()
                if not temp:
                    raise LuaPreprocessorException("Wrong token for filter: expected filter2")
                ret = temp
            return self.filter(ftype, ref, ret)
        elif token == 'variable':
            ftype = token_store.popleft()
            ref = lexer.get_token()
            temp = lexer.get_token()
            if temp != 'to':
                raise LuaPreprocessorException("Wrong token for filter: exptected 'to', got {0}".format(repr(temp)))
            ret = lexer.get_token()
            return self.variable(ftype, ref, ret)
        else:
            raise LuaPreprocessorException("Wrong command: "+repr(lexer.instream.getvalue()))

    def options(self, key, value):
        if key == 'delimiter':
            self.delimiter = value[1:-1]
        else:
            raise LuaPreprocessorException("Wrong option: "+repr(key))

    def server_start(self, ctype, sname, opts):
        if sname not in self.servers:
            raise LuaPreprocessorException('Can\'t start nonexistent server '+repr(sname))
        self.servers[sname].start(silent=True)
        self.connections[sname] = self.servers[sname].admin
        try:
            self.connections[sname]('return true', silent=True)
        except socket.error as e:
            LuaPreprocessorException('Can\'t start server '+repr(sname))

    def server_stop(self, ctype, sname, opts):
        if sname not in self.servers:
            raise LuaPreprocessorException('Can\'t stop nonexistent server '+repr(sname))
        self.connections[sname].disconnect()
        self.connections.pop(sname)
        self.servers[sname].stop()

    def server_create(self, ctype, sname, opts):
        if sname in self.servers:
            raise LuaPreprocessorException('Server {0} already exists'.format(repr(sname)))
        temp = self.create_server()
        temp.name = sname
        for flag in ['wait', 'wait_load']:
            opts[flag] = bool(literal_eval(opts.get(flag, '1')))
        if 'need_init' in opts:
            temp.need_init   = True if opts['need_init'] == 'True' else False
        if 'script' in opts:
            temp.script = opts['script'][1:-1]
        if 'lua_libs' in opts:
            temp.lua_libs = opts['lua_libs'][1:-1].split(' ')
        temp.rpl_master = None
        if 'rpl_master' in opts:
            temp.rpl_master = self.servers[opts['rpl_master']]
        temp.vardir = self.suite_ini['vardir']
        temp.inspector_port = int(self.suite_ini.get(
            'inspector_port', temp.DEFAULT_INSPECTOR
        ))
        self.servers[sname] = temp
        if 'workdir' not in opts:
            self.servers[sname].deploy(silent=True, **opts)
        else:
            copy_from = opts['workdir']
            copy_to = self.servers[sname].name
            self.servers[sname].install(silent=True)
            os.system('rm -rf %s/%s' % (
                self.servers[sname].vardir, copy_to
            ))
            os.system('cp -r %s %s/%s' % (
                copy_from,
                self.servers[sname].vardir,
                copy_to
            ))
        nmsp = Namespace()
        setattr(nmsp, 'admin', temp.admin.port)
        setattr(nmsp, 'listen', temp.iproto.port)
        if temp.rpl_master:
            setattr(nmsp, 'master', temp.rpl_master.iproto.port)
        setattr(self.environ, sname, nmsp)

    def server_deploy(self, ctype, sname, opts):
        self.servers[sname].deploy()

    def server_cleanup(self, ctype, sname, opts):
        if sname not in self.servers:
            raise LuaPreprocessorException('Can\'t cleanup nonexistent server '+repr(sname))
        self.servers[sname].cleanup()
        if sname != 'default':
            if hasattr(self.environ, sname):
                delattr(self.environ, sname)
        else:
            self.servers[sname].install(silent=True)

    def server_delete(self, ctype, sname, opts):
        if sname not in self.servers:
            raise LuaPreprocessorException('Can\'t cleanup nonexistent server '+repr(sname))
        self.servers[sname].cleanup()
        if sname != 'default':
            if hasattr(self.environ, sname):
                delattr(self.environ, sname)
            del self.servers[sname]

    def switch(self, server):
        self.lua_eval(server, "env=require('test_run')", silent=True)
        self.lua_eval(
            server, "test_run=env.new()", silent=True
        )
        return self.connection('set', [server, ], None)

    def server_restart(self, ctype, sname, opts):
        # self restart from lua with proxy
        if 'proxy' not in self.servers:
            self.server_create(
                'create', 'proxy', {'script': '"box/proxy.lua"'}
            )
        self.server_start('start', 'proxy', {})
        self.switch('proxy')

        # restart real server and switch back
        self.server_stop(ctype, sname, opts)
        if 'cleanup' in opts:
            self.server_cleanup(ctype, sname, opts)
            self.server_deploy(ctype, sname, opts)
        self.server_start(ctype, sname, opts)
        self.switch(sname)

        # remove proxy
        self.server_stop('stop', 'proxy', {})

    def server(self, ctype, sname, opts):
        attr = 'server_%s' % ctype
        if hasattr(self, attr):
            getattr(self, attr)(ctype, sname, opts)
        else:
            raise LuaPreprocessorException(
                'Unknown command for server: %s' % ctype
            )

    def wait_lsn(self, waiter, master):
        if waiter not in self.servers:
            raise LuaPreprocessorException('Can\'t start nonexistent server %s' % repr(waiter))
        if master not in self.servers:
            raise LuaPreprocessorException('Can\'t start nonexistent server %s' % repr(master))
        replica = self.servers[waiter]
        wait_for = self.servers[master]
        master_id = wait_for.get_param('server')['id']
        lsn = wait_for.get_lsn(master_id)
        replica.wait_lsn(master_id, lsn)

    def connection(self, ctype, cnames, sname):
        # we always get a list of connections as input here
        cname = cnames[0]
        if ctype == 'create':
            if sname not in self.servers:
                raise LuaPreprocessorException('Can\'t create connection to nonexistent server '+repr(sname))
            if cname in self.connections:
                raise LuaPreprocessorException('Connection {0} already exists'.format(repr(cname)))
            self.connections[cname] = AdminAsyncConnection('localhost', self.servers[sname].admin.port)
            self.connections[cname].connect()
        elif ctype == 'drop':
            if cname not in self.connections:
                raise LuaPreprocessorException('Can\'t drop nonexistent connection '+repr(cname))
            self.connections[cname].disconnect()
            self.connections.pop(cname)
        elif ctype == 'set':
            for i in cnames:
                if not i in self.connections:
                    raise LuaPreprocessorException('Can\'t set nonexistent connection '+repr(cname))
            self.curcon = [self.connections[i] for i in cnames]
        else:
            raise LuaPreprocessorException('Unknown command for connection: '+repr(ctype))

    def filter(self, ctype, ref, ret):
        if ctype == 'push':
            sys.stdout.push_filter(ref[1:-1], ret[1:-1])
        elif ctype == 'pop':
            sys.stdout.pop_filter()
        elif ctype == 'clear':
            sys.stdout.clear_all_filters()
        else:
            raise LuaPreprocessorException("Wrong command for filters: " + repr(ctype))

    def lua_eval(self, name, expr, silent=True):
        self.servers[name].admin.reconnect()
        result = self.servers[name].admin(
            '%s%s' % (expr, self.delimiter), silent=silent
        )
        result = yaml.load(result)
        if not result:
            result = []
        return result


    def variable(self, ctype, ref, ret):
        if ctype == 'set':
            self.curcon[0].reconnect()
            self.curcon[0](ref+'='+str(eval(ret[1:-1], {}, self.environ.__dict__)), silent=True)
        else:
            raise LuaPreprocessorException("Wrong command for variables: " + repr(ctype))

    def __call__(self, string):
        string = string[3:].strip()
        self.parse_preprocessor(string)

    def cleanup(self):
        sys.stdout.clear_all_filters()
        # don't stop the default server
        self.servers.pop('default')
        for k, v in self.servers.iteritems():
            v.stop(silent=True)
            v.cleanup()
            if k in self.connections:
                self.connections[k].disconnect()
                self.connections.pop(k)

