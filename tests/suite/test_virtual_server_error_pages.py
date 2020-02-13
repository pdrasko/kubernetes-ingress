import pytest
import json
import requests

from suite.custom_assertions import wait_and_assert_status_code, assert_vs_conf_not_exists, \
    assert_event_starts_with_text_and_contains_errors
from settings import TEST_DATA
from suite.custom_resources_utils import patch_virtual_server_from_yaml
from suite.resources_utils import wait_before_test, get_first_pod_name, get_events


@pytest.mark.vs
@pytest.mark.parametrize('crd_ingress_controller, virtual_server_setup',
                         [({"type": "complete", "extra_args": [f"-enable-custom-resources"]},
                           {"example": "virtual-server-error-pages", "app_type": None})],
                         indirect=True)
class TestVSErrorPages:
    def test_redirect_strategy(self, kube_apis, crd_ingress_controller, virtual_server_setup):
        wait_and_assert_status_code(307, virtual_server_setup.backend_1_url,
                                    virtual_server_setup.vs_host, allow_redirects=False)
        resp = requests.get(virtual_server_setup.backend_1_url,
                            headers={"host": virtual_server_setup.vs_host}, allow_redirects=False)
        assert f'http://{virtual_server_setup.vs_host}/error_307.html' in resp.next.url

    def test_return_strategy(self, kube_apis, crd_ingress_controller, virtual_server_setup):
        wait_and_assert_status_code(207, virtual_server_setup.backend_2_url, virtual_server_setup.vs_host)
        resp = requests.get(virtual_server_setup.backend_2_url,
                            headers={"host": virtual_server_setup.vs_host})
        resp_content = json.loads(resp.content)
        assert resp_content['status'] == '207' \
            and resp_content['message'] == 'Forbidden' \
            and resp.headers.get('x-debug-original-status') == '207'

    def test_virtual_server_after_update(self, kube_apis, crd_ingress_controller, virtual_server_setup):
        patch_virtual_server_from_yaml(kube_apis.custom_objects, virtual_server_setup.vs_name,
                                       f"{TEST_DATA}/virtual-server-error-pages/virtual-server-updated.yaml",
                                       virtual_server_setup.namespace)
        wait_and_assert_status_code(301, virtual_server_setup.backend_1_url,
                                    virtual_server_setup.vs_host, allow_redirects=False)
        resp = requests.get(virtual_server_setup.backend_1_url,
                            headers={"host": virtual_server_setup.vs_host, "x-forwarded-proto": "http"},
                            allow_redirects=False)
        assert f'http://{virtual_server_setup.vs_host}/error_301_http.html' in resp.next.url

        wait_and_assert_status_code(502, virtual_server_setup.backend_2_url, virtual_server_setup.vs_host)
        resp = requests.get(virtual_server_setup.backend_2_url,
                            headers={"host": virtual_server_setup.vs_host})
        resp_content = resp.content.decode('utf-8')
        assert resp_content == 'Hello World!\n'

    def test_validation_event_flow(self, kube_apis, ingress_controller_prerequisites, crd_ingress_controller,
                                   virtual_server_setup):
        err_text = "Invalid value: \"schema\": " \
                   "'schema' contains an invalid NGINX variable. Accepted variables are: status"
        invalid_fields = [
            "spec.routes[0].errorPages[0].codes: Required value: must include at least 1 status code in `codes`",
            "spec.routes[1].errorPages[0].return.body: Required value",
            f"spec.routes[1].errorPages[0].return.headers[0].value: {err_text}"
        ]
        text = f"{virtual_server_setup.namespace}/{virtual_server_setup.vs_name}"
        vs_event_text = f"VirtualServer {text} is invalid and was rejected: "
        vs_file = f"{TEST_DATA}/virtual-server-error-pages/virtual-server-invalid.yaml"
        patch_virtual_server_from_yaml(kube_apis.custom_objects,
                                       virtual_server_setup.vs_name,
                                       vs_file,
                                       virtual_server_setup.namespace)
        wait_before_test(2)
        ic_pod_name = get_first_pod_name(kube_apis.v1, ingress_controller_prerequisites.namespace)
        vs_events = get_events(kube_apis.v1, virtual_server_setup.namespace)

        assert_event_starts_with_text_and_contains_errors(vs_event_text, vs_events, invalid_fields)
        assert_vs_conf_not_exists(kube_apis, ic_pod_name, ingress_controller_prerequisites.namespace,
                                  virtual_server_setup)

    @pytest.mark.parametrize('v_s_data', [
        {"src": "virtual-server-splits.yaml", "expected_code": 308},
        {"src": "virtual-server-matches.yaml", "expected_code": 307}
    ])
    def test_splits_and_matches(self, kube_apis, crd_ingress_controller, virtual_server_setup, v_s_data):
        patch_virtual_server_from_yaml(kube_apis.custom_objects, virtual_server_setup.vs_name,
                                       f"{TEST_DATA}/virtual-server-error-pages/{v_s_data['src']}",
                                       virtual_server_setup.namespace)
        wait_and_assert_status_code(v_s_data['expected_code'], virtual_server_setup.backend_1_url,
                                    virtual_server_setup.vs_host, allow_redirects=False)
        resp = requests.get(virtual_server_setup.backend_1_url,
                            headers={"host": virtual_server_setup.vs_host}, allow_redirects=False)
        assert f'http://{virtual_server_setup.vs_host}/error_{v_s_data["expected_code"]}.html' in resp.next.url
