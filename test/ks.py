from kubernetes.client import api_client
from kubernetes.client.apis import core_v1_api


def test_service_apis():
    from kubernetes import client
    k8s_url = 'http://192.168.137.61:8080'
    # with open('/kube/auth/token.txt', 'r') as file:
    #     Token = file.read().strip('\n')

    configuration = client.Configuration()
    configuration.host = k8s_url

    # configuration.verify_ssl = False
    # configuration.api_key = {"authorization": "Bearer " + Token}


    client1 = api_client.ApiClient(configuration=configuration)
    api = core_v1_api.CoreV1Api(client1)
    # ret = api.list_pod_for_all_namespaces(watch=False)
    # print(ret)
    import json
    from lib.json_helper import format_json_dumps

    result = api.list_replication_controller_for_all_namespaces()

    print format_json_dumps(result.to_dict().items()[0][1])


test_service_apis()