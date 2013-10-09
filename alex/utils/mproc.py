#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This code is mostly PEP8-compliant. See
# http://www.python.org/dev/peps/pep-0008/.

"""
Implements useful classes for handling multiprocessing implementation of
the Alex system.
"""

import functools
import multiprocessing
import threading
import fcntl
import time
import os
import sys
import re
import codecs
import traceback

from datetime import datetime


def local_lock():
    """This decorator makes the decorated function thread safe.

    For each function it creates a unique lock.

    """
    lock = multiprocessing.Lock()

    def decorator(user_function):
        @functools.wraps(user_function)
        def wrapper(*args, **kw):
            lock.acquire()
            try:
                return user_function(*args, **kw)
            except Exception as e:
                raise e
            finally:
                lock.release()

        return wrapper

    return decorator


def global_lock(lock):
    """This decorator makes the decorated function thread safe.

    Keyword arguments:
        lock -- a global variable pointing to the object to lock on

    """
    def decorator(user_function):
        @functools.wraps(user_function)
        def wrapper(*args, **kw):
            lock.acquire()
            try:
                return user_function(*args, **kw)
            except Exception as e:
                raise e
            finally:
                lock.release()

        return wrapper

    return decorator


def file_lock(file_name):
    """ Multiprocessing lock using files. Lock on a specific file.
    """
    lock_file = codecs.open(file_name, 'w', encoding='utf8')
    fcntl.lockf(lock_file, fcntl.LOCK_EX)
    return lock_file


def file_unlock(lock_file):
    """ Multiprocessing lock using files. Unlock on a specific file.
    """
    fcntl.lockf(lock_file, fcntl.LOCK_UN)
    lock_file.close()

def async(func):
    """4
        A function decorator intended to make "func" run in a separate thread (asynchronously).
        Returns the created Thread object

        E.g.:
        @run_async
        def task1():
            do_something

        @run_async
        def task2():
            do_something_too

        t1 = task1()
        t2 = task2()
        ...
        t1.join()
        t2.join()
    """

    @functools.wraps(func)
    def async_func(*args, **kwargs):
        func_hl = threading.Thread(target = func, args = args, kwargs = kwargs)
        func_hl.start()
        return func_hl

    return async_func


class InstanceID(object):
    """
    This class provides unique ids to all instances of objects inheriting
    from this class.

    """

    lock = multiprocessing.Lock()
    instance_id = multiprocessing.Value('i', 0)

    @global_lock(lock)
    def get_instance_id(self):
        InstanceID.instance_id.value += 1
        return InstanceID.instance_id.value


class SystemLogger(object):
    """
    This is a multiprocessing-safe logger.  It should be used by all components
    in Alex.

    """

    lock = multiprocessing.RLock()
    levels = {
        'SYSTEM-LOG':       0,
        'DEBUG':           10,
        'INFO':            20,
        'WARNING':         30,
        'CRITICAL':        40,
        'EXCEPTION':       50,
        'ERROR':           60,
    }

    def __init__(self, output_dir, stdout_log_level='DEBUG', stdout=True,
                 file_log_level='DEBUG'):
        self.stdout_log_level = stdout_log_level
        self.stdout = stdout
        self.file_log_level = file_log_level
        self.output_dir = output_dir

        if not os.path.exists(output_dir):
            os.mkdir(output_dir)

        # Create a buffer of size 1000 bytes in shared memory to hold
        # the name of the logging directory for current session.
        self.current_session_log_dir_name = multiprocessing.Array('c', ' ' * 1000)
        self.current_session_log_dir_name.value = ''
        self._session_started = False

    def __repr__(self):
        return ("SystemLogger(output_dir={outdir}, stdout_log_level='"
                "{lvl_out}', stdout={stdout}, file_log_level='{lvl_f}')"
                ).format(lvl_out=self.stdout_log_level, stdout=self.stdout,
                         lvl_f=self.file_log_level, outdir=self.output_dir)

    def get_time_str(self):
        """ Return current time in dashed ISO-like format.

        It is useful in constructing file and directory names.

        """
        return '{dt}-{tz}'.format(dt=datetime.now().strftime('%Y-%m-%d-%H-%M-%S.%f'),
            tz=time.tzname[time.localtime().tm_isdst])

    @global_lock(lock)
    def session_start(self, remote_uri):
        """ Create a specific directory for logging a specific call.

        NOTE: This is not completely safe. It can be called from several
        processes.

        """
        session_name = self.get_time_str() + '-' + remote_uri
        self.current_session_log_dir_name.value = os.path.join(self.output_dir, session_name)
        os.makedirs(self.current_session_log_dir_name.value)
        self._session_started = True

    @global_lock(lock)
    def session_end(self):
        """ Disable logging into the call-specific directory.
        """
        self.current_session_log_dir_name.value = ''
        self._session_started = False

    @global_lock(lock)
    def _get_session_started(self):
        return self._session_started

    session_started = property(_get_session_started)

    # XXX: Returning the enclosing directory in case the session has been
    # closed may not be ideal. In some cases, it causes session logs to be
    # written to outside the related session directory, which is no good.
    @global_lock(lock)
    def get_session_dir_name(self):
        """ Return directory where all the call related files should be stored.
        """
        if self.current_session_log_dir_name.value:
        # This should be equivalent and more accurate. (Matěj)
        # if self._session_started:
            return self.current_session_log_dir_name.value

        # back off to the default logging directory
        return self.output_dir

    @global_lock(lock)
    def formatter(self, lvl, message):
        """ Format the message - pretty print
        """
        s = self.get_time_str()
        s += u'  %-10s : ' % multiprocessing.current_process().name
        s += u'%-10s ' % lvl
        s += u'\n'

        ss = u'    ' + unicode(message)
        ss = re.sub(r'\n', '\n    ', ss)

        return s + ss + '\n'

    @global_lock(lock)
    def log(self, lvl, message, session_system_log=False):
        """
        Logs the message based on its level and the logging setting.
        Before writing into a logging file, it locks the file.

        """

        if self.stdout:
            # Log to stdout.
            if (SystemLogger.levels[lvl] >=
                    SystemLogger.levels[self.stdout_log_level]):
                print self.formatter(lvl, message)
                sys.stdout.flush()

        if self.output_dir:
            if (SystemLogger.levels[lvl] >=
                    SystemLogger.levels[self.file_log_level]):
                # Log to the global log.
                log_fname = os.path.join(self.output_dir, 'system.log')
                with codecs.open(log_fname, "a+", encoding='utf8',
                                 buffering=0) as log_file:
                    fcntl.lockf(log_file, fcntl.LOCK_EX)
                    log_file.write(self.formatter(lvl, message))
                    log_file.write('\n')
                    fcntl.lockf(log_file, fcntl.LOCK_UN)

        if self.current_session_log_dir_name.value:
            if (session_system_log
                or SystemLogger.levels[lvl] >=
                    SystemLogger.levels[self.file_log_level]):
                # Log to the call-specific log.
                session_log_fname = os.path.join(
                    self.current_session_log_dir_name.value, 'system.log')
                with codecs.open(session_log_fname, "a+", encoding='utf8',
                                 buffering=0) as session_log_file:
                    fcntl.lockf(session_log_file, fcntl.LOCK_EX)
                    session_log_file.write(self.formatter(lvl, message))
                    session_log_file.write('\n')
                    fcntl.lockf(session_log_file, fcntl.LOCK_UN)

    @global_lock(lock)
    def info(self, message):
        self.log('INFO', message)

    @global_lock(lock)
    def debug(self, message):
        self.log('DEBUG', message)

    @global_lock(lock)
    def warning(self, message):
        self.log('WARNING', message)

    @global_lock(lock)
    def critical(self, message):
        self.log('CRITICAL', message)

    @global_lock(lock)
    def exception(self, message):
        tb = traceback.format_exc()
        self.log('EXCEPTION', unicode(message) + '\n' + unicode(tb, 'utf8'))

    @global_lock(lock)
    def error(self, message):
        self.log('ERROR', message)

    @global_lock(lock)
    def session_system_log(self, message):
        """This logs specifically only into the call-specific system log."""
        self.log('SYSTEM-LOG', message, session_system_log=True)
