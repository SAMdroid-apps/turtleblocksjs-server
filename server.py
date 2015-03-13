#!/usr/bin/env python

# Copyright (c) 2014 Martin Abente Lahaye. - tch@sugarlabs.org
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA

import os
import json
import logging
import SimpleHTTPServer
import SocketServer

from tempfile import mkstemp
from subprocess import check_output
from md5 import md5

from settings import Settings


def authorize(method):
    """ just a basic method for authorization """
    def verify(handler, *args, **kwargs):
        if 'x-api-key' not in handler.headers or \
                handler.headers['x-api-key'] != Settings.API_KEY:
            handler.send_response(401, "unauthorized")
            handler.end_headers()
            return None
        return method(handler, *args, **kwargs)
    return verify


def check(method):
    """ put things under control """
    def verify(handler, *args, **kwargs):
        project_id = get_project_id(handler)
        if project_id and project_id.find('/') >= 0:
            handler.send_response(403, 'forbidden')
            handler.end_headers()
            return None
        if project_id and check_if_missing(method, handler):
            handler.send_response(404, 'not found')
            handler.end_headers()
            return None
        return method(handler, *args, **kwargs)
    return verify


def get_project_id(handler):
    return handler.path.replace('/', '')


def get_project_path(handler):
    project_id = get_project_id(handler)
    return os.path.join(Settings.PROJECTS, project_id)


def get_all_projects():
    filenames = []
    for filename in os.listdir(Settings.PROJECTS):
        filenames.append(filename)
    return json.dumps(filenames)


def get_one_project(handler):
    path = get_project_path(handler)
    with open(path, 'r') as file:
        return file.read()


def check_if_missing(method, handler):
    if method.__name__ == 'do_GET' and \
       not os.path.isfile(get_project_path(handler)):
        return True
    return False


def check_projects_path():
    """Create the project folders if its didn't exists"""
    if not os.path.exists(Settings.PROJECTS):
        os.mkdir(Settings.PROJECTS)


def datauri_contents(data):
    # The python b64 decoder does not deal with edge cases. It raises
    # exceptions decoding b64 from Turtle and decodes it incorrectly in
    # other cases. The base64 command is much more robust.
    fd, p = mkstemp()
    with os.fdopen(fd, 'w') as f:
        f.write(data[len('data:image/png;base64,'):])

    with open(p) as f:
        data = check_output(['base64', '-d'], stdin=f)
    os.remove(p)

    return data


def etag(data):
    return '"{}"'.format(md5(data).hexdigest())


class ServerHandler(SimpleHTTPServer.SimpleHTTPRequestHandler):

    def cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods',
                         'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers',
                         'x-project-id, x-api-key')

    def do_OPTIONS(self):
        logging.info(self.headers)
        self.send_response(200, 'ok')
        self.cors()

    @check
    def do_GET(self):
        content_type = 'application/json'
        if get_project_id(self):
            body = get_one_project(self)
            if body.startswith('data:image/png;base64,'):
                body = datauri_contents(body)

            if body.startswith('\x89PNG'):
                content_type = 'image/png'
        else:
            body = get_all_projects()

        browser_has_cache = \
            self.headers.getheader('If-None-Match', '') == etag(body)

        response_code = 200
        if browser_has_cache:
            response_code = 304
        self.send_response(response_code)
        self.cors()

        self.send_header('Content-type', content_type)
        if content_type == 'image/png':
            self.send_header('Cache-Control', 'public; max-age=31536000')
            self.send_header('Etag', etag(body))
        self.end_headers()
        if not browser_has_cache:
            self.wfile.write(body)

    @authorize
    @check
    def do_POST(self):
        self.send_response(200)
        self.cors()
        self.end_headers()

        content_len = int(self.headers.getheader('content-length', 0))
        content = self.rfile.read(content_len)

        if content.startswith('data:image/png;base64,'):
            content = datauri_contents(content)

        path = get_project_path(self)
        with open(path, 'w') as file:
            file.write(content)

if __name__ == '__main__':
    check_projects_path()
    httpd = SocketServer.TCPServer((Settings.ADDRESS,
                                    Settings.PORT),
                                   ServerHandler)
    print 'Starting server on {}:{}'.format(Settings.ADDRESS, Settings.PORT)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass

    httpd.server_close()
