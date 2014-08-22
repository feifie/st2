from functools import wraps
import httplib
from urlparse import urljoin
from oslo.config import cfg

from flask import (jsonify, request, Flask)


HOST = cfg.CONF.generic_webhook_sensor.host
PORT = cfg.CONF.generic_webhook_sensor.port
BASE_URL = cfg.CONF.generic_webhook_sensor.url

PARAMETERS_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {"type": "string"}
    },
    "required": ['url'],
    "additionalProperties": False
}

PAYLOAD_SCHEMA = {
    "type": "object"
}


# Dectorators for request validations.
def validate_json(f):
    @wraps(f)
    def wrapper(*args, **kw):
        try:
            request.json
        except Exception:
            msg = 'Content-Type must be application/json.'
            return jsonify({'error': msg}), httplib.BAD_REQUEST
        return f(*args, **kw)
    return wrapper


class St2GenericWebhooksSensor(object):
    def __init__(self, container_service):
        self._container_service = container_service
        self._log = self._container_service.get_logger(self.__class__.__name__)
        self._host = HOST
        self._port = PORT
        self._app = Flask(__name__)
        self._hooks = {}

    def setup(self):
        @self._app.route(urljoin(BASE_URL, '<path:url>'), methods=['POST'])
        def _handle_webhook(url):
            webhook_body = request.get_json()

            try:
                trigger = self._hooks[url]
            except KeyError:
                self._log.info('Got request for a hook that have not been registered yet: %s',
                               url)
                return '', httplib.NOT_FOUND

            try:
                self._container_service.dispatch(trigger, webhook_body)
            except Exception as e:
                self._log.exception('Exception %s handling webhook', e)
                return jsonify({'error': str(e)}), httplib.INTERNAL_SERVER_ERROR

            # From rfc2616 sec 10.2.3 202 Accepted
            # "The entity returned with this response SHOULD include an indication of the request's
            # current status and either a pointer to a status monitor or some estimate of when the
            # user can expect the request to be fulfilled."
            # We should either pick another status code or, better, find a way to provide a
            # reference for the actionexecution that have been created during that call.
            return jsonify({}), httplib.ACCEPTED

    def start(self):
        self._app.run(port=self._port, host=self._host)

    def stop(self):
        # If Flask is using the default Werkzeug server, then call shutdown on it.
        func = request.environ.get('werkzeug.server.shutdown')
        if func is None:
            raise RuntimeError('Not running with the Werkzeug Server')
        func()

    def add_trigger(self, trigger):
        url = trigger['parameters']['url']
        self._log.info('Listening to endpoint: %s', urljoin(BASE_URL, url))
        self._hooks[url] = trigger

    def update_trigger(self, trigger):
        pass

    def remove_trigger(self, trigger):
        url = trigger['parameters']['url']
        self._log.info('Stop listening to endpoint: %s', urljoin(BASE_URL, url))
        del self._hooks[url]

    def get_trigger_types(self):
        return [{
            'name': 'st2.webhook',
            'description': 'Relays a Trigger POSTed to the supplied URL. The supplied url is used '
                           'as a suffix of http://<stanley-host>:%s/{URL}.' % str(self._port),
            'payload_schema': PAYLOAD_SCHEMA,
            'parameters_schema': PARAMETERS_SCHEMA
        }]
