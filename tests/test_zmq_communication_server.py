import socket
from datetime import datetime

from gevent import monkey

import core.case.database as case_database
import core.case.subscription
import core.config.paths
import core.controller
from server import flaskserver as flask_server
from server.returncodes import *
from tests.util.case_db_help import executed_actions, setup_subscriptions_for_action
from tests.util.servertestcase import ServerTestCase
from tests.util.thread_control import modified_setup_worker_env

try:
    from importlib import reload
except ImportError:
    from imp import reload


class TestWorkflowServer(ServerTestCase):
    patch = False

    def setUp(self):
        monkey.patch_socket()
        core.case.subscription.subscriptions = {}
        case_database.initialize()

    def tearDown(self):
        core.controller.workflows = {}
        core.case.subscription.clear_subscriptions()
        for case in core.case.database.case_db.session.query(core.case.database.Case).all():
            core.case.database.case_db.session.delete(case)
        core.case.database.case_db.session.commit()
        reload(socket)

    def test_execute_workflow(self):
        flask_server.running_context.controller.initialize_threading(worker_environment_setup=modified_setup_worker_env)
        workflow = flask_server.running_context.controller.get_workflow('test', 'helloWorldWorkflow')
        action_uids = [action.uid for action in workflow.actions.values() if action.name == 'start']
        setup_subscriptions_for_action(workflow.uid, action_uids)
        start = datetime.utcnow()

        response = self.post_with_status_check('/api/playbooks/test/workflows/helloWorldWorkflow/execute',
                                               headers=self.headers,
                                               status_code=SUCCESS_ASYNC)
        flask_server.running_context.controller.shutdown_pool(1)
        self.assertIn('id', response)
        actions = []
        for uid in action_uids:
            actions.extend(executed_actions(uid, start, datetime.utcnow()))
        self.assertEqual(len(actions), 1)
        action = actions[0]
        result = action['data']
        self.assertEqual(result, {'status': 'Success', 'result': 'REPEATING: Hello World'})

    def test_read_all_results(self):
        flask_server.running_context.controller.initialize_threading(worker_environment_setup=modified_setup_worker_env)
        self.app.post('/api/playbooks/test/workflows/helloWorldWorkflow/execute', headers=self.headers)
        self.app.post('/api/playbooks/test/workflows/helloWorldWorkflow/execute', headers=self.headers)
        self.app.post('/api/playbooks/test/workflows/helloWorldWorkflow/execute', headers=self.headers)

        with flask_server.running_context.flask_app.app_context():
            flask_server.running_context.controller.shutdown_pool(3)

        response = self.get_with_status_check('/api/workflowresults', headers=self.headers)
        self.assertEqual(len(response), 3)

        for result in response:
            self.assertSetEqual(set(result.keys()), {'status', 'completed_at', 'started_at', 'name', 'results', 'uid'})
            for action_result in result['results']:
                self.assertSetEqual(set(action_result.keys()), {'arguments', 'type', 'name', 'timestamp', 'result', 'app_name', 'action_name'})