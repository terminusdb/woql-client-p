import os
import subprocess
import time

import pytest
import requests

MAX_CONTAINER_STARTUP_TIME = 30


def is_docker_installed():
    try:
        output = subprocess.run(["docker", "--version"], stderr=subprocess.PIPE)
    except FileNotFoundError:
        return False
    return output.returncode == 0


pytestmark = pytest.mark.skipif(
    not is_docker_installed(), reason="docker not installed"
)


@pytest.fixture(scope="module")
def test_csv():
    with open(os.path.dirname(os.path.abspath(__file__)) + "/test_csv.csv") as reader:
        csv = reader.read()
    return csv


@pytest.fixture(scope="module")
def terminusx_token():
    os.environ["TERMINUSDB_ACCESS_TOKEN"] = os.environ.get("TERMINUSX_TOKEN")
    return os.environ["TERMINUSDB_ACCESS_TOKEN"]


@pytest.fixture(scope="module")
def docker_url_jwt(pytestconfig):
    # we are using subprocess in case we need to access some of the outputs
    # most likely
    jwt_token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6InRlc3RrZXkifQ.eyJodHRwOi8vdGVybWludXNkYi5jb20vc2NoZW1hL3N5c3RlbSNhZ2VudF9uYW1lIjoiYWRtaW4iLCJodHRwOi8vdGVybWludXNkYi5jb20vc2NoZW1hL3N5c3RlbSN1c2VyX2lkZW50aWZpZXIiOiJhZG1pbkB1c2VyLmNvbSIsImlzcyI6Imh0dHBzOi8vdGVybWludXNodWIuZXUuYXV0aDAuY29tLyIsInN1YiI6ImFkbWluIiwiYXVkIjpbImh0dHBzOi8vdGVybWludXNodWIvcmVnaXN0ZXJVc2VyIiwiaHR0cHM6Ly90ZXJtaW51c2h1Yi5ldS5hdXRoMC5jb20vdXNlcmluZm8iXSwiaWF0IjoxNTkzNzY5MTgzLCJhenAiOiJNSkpuZEdwMHpVZE03bzNQT1RRUG1SSkltWTJobzBhaSIsInNjb3BlIjoib3BlbmlkIHByb2ZpbGUgZW1haWwifQ.Ru03Bi6vSIQ57bC41n6fClSdxlb61m0xX6Q34Yh91gql0_CyfYRWTuqzqPMFoCefe53hPC5E-eoSFdID_u6w1ih_pH-lTTqus9OWgi07Qou3QNs8UZBLiM4pgLqcBKs0N058jfg4y6h9GjIBGVhX9Ni2ez3JGNcz1_U45BhnreE"
    pytestconfig.getoption("docker_compose")
    output = subprocess.run(
        [
            "docker",
            "compose",
            "--file",
            os.path.dirname(os.path.realpath(__file__))
            + "/test-docker-compose-jwt.yml",
            "up",
            "-d",
        ],
        stderr=subprocess.PIPE,
    )
    if output.returncode != 0:
        raise RuntimeError(output.stderr)

    test_url = "http://127.0.0.1:6367"
    is_server_started = False

    seconds_waited = 0
    while not is_server_started:
        service = subprocess.run(
            [
                "docker",
                "compose",
                "--file",
                os.path.dirname(os.path.realpath(__file__))
                + "/test-docker-compose-jwt.yml",
                "ps",
                "--services",
                "--filter",
                "status=running",
            ],
            stdout=subprocess.PIPE,
            check=True,
        )

        if service.stdout == b"terminusdb-server\n":
            try:
                response = requests.get(test_url)
                assert response.status_code == 200
                break
            except (requests.exceptions.ConnectionError, AssertionError):
                pass

        seconds_waited += 1
        time.sleep(1)

        if seconds_waited > MAX_CONTAINER_STARTUP_TIME:
            clean_up_container()
            raise RuntimeError("Container was to slow to startup")

    yield (test_url, jwt_token)
    clean_up_container()


@pytest.fixture(scope="module")
def docker_url(pytestconfig):
    # we are using subprocess in case we need to access some of the outputs
    # most likely
    pytestconfig.getoption("docker_compose")
    output = subprocess.run(
        [
            "docker",
            "compose",
            "--file",
            os.path.dirname(os.path.realpath(__file__)) + "/test-docker-compose.yml",
            "up",
            "-d",
        ],
        stderr=subprocess.PIPE,
    )
    if output.returncode != 0:
        raise RuntimeError(output.stderr)

    test_url = "http://127.0.0.1:6366"
    is_server_started = False

    seconds_waited = 0
    while not is_server_started:
        service = subprocess.run(
            [
                "docker",
                "compose",
                "--file",
                os.path.dirname(os.path.realpath(__file__))
                + "/test-docker-compose.yml",
                "ps",
                "--services",
                "--filter",
                "status=running",
            ],
            stdout=subprocess.PIPE,
            check=True,
        )

        if service.stdout == b"terminusdb-server\n":
            try:
                response = requests.get(test_url)
                assert response.status_code == 200
                break
            except (requests.exceptions.ConnectionError, AssertionError):
                pass

        seconds_waited += 1
        time.sleep(1)

        if seconds_waited > MAX_CONTAINER_STARTUP_TIME:
            clean_up_container()
            raise RuntimeError("Container was to slow to startup")

    yield test_url
    clean_up_container()


def clean_up_container():
    subprocess.run(
        [
            "docker",
            "compose",
            "--file",
            os.path.dirname(os.path.realpath(__file__)) + "/test-docker-compose.yml",
            "down",
        ],
        check=True,
    )
    subprocess.run(
        [
            "docker",
            "compose",
            "--file",
            os.path.dirname(os.path.realpath(__file__)) + "/test-docker-compose.yml",
            "rm",
            "--force",
            "--stop",
            "-v",
        ],
        check=True,
    )
    subprocess.run(
        [
            "docker",
            "compose",
            "--file",
            os.path.dirname(os.path.realpath(__file__))
            + "/test-docker-compose-jwt.yml",
            "down",
        ],
        check=True,
    )
    subprocess.run(
        [
            "docker",
            "compose",
            "--file",
            os.path.dirname(os.path.realpath(__file__))
            + "/test-docker-compose-jwt.yml",
            "rm",
            "--force",
            "--stop",
            "-v",
        ],
        check=True,
    )
    subprocess.run(["docker", "compose", "down"])
    subprocess.run(["docker", "compose", "rm", "--force", "--stop", "-v"])


@pytest.fixture(scope="module")
def one_class_obj():
    return {
        "@type": "api:WoqlResponse",
        "api:status": "api:success",
        "api:variable_names": [
            "Class ID",
            "Class Name",
            "Description",
            "Parents",
            "Children",
            "Abstract",
        ],
        "bindings": [
            {
                "Abstract": {
                    "@type": "http://www.w3.org/2001/XMLSchema#string",
                    "@value": "No",
                },
                "Children": {
                    "@type": "http://www.w3.org/2001/XMLSchema#string",
                    "@value": "",
                },
                "Class ID": "terminusdb:///schema#Journey",
                "Class Name": {
                    "@type": "http://www.w3.org/2001/XMLSchema#string",
                    "@value": "Bike Journey",
                },
                "Description": {
                    "@type": "http://www.w3.org/2001/XMLSchema#string",
                    "@value": "Bike Journey object that capture each bike joourney.",
                },
                "Parents": ["http://terminusdb.com/schema/system#Document"],
            }
        ],
        "deletes": 0,
        "inserts": 0,
        "transaction_retry_count": 0,
    }


@pytest.fixture(scope="module")
def one_class_prop():
    return {
        "@type": "api:WoqlResponse",
        "api:status": "api:success",
        "api:variable_names": [
            "Property ID",
            "Property Name",
            "Property Domain",
            "Property Type",
            "Property Range",
            "Property Description",
        ],
        "bindings": [
            {
                "Property Description": {
                    "@type": "http://www.w3.org/2001/XMLSchema#string",
                    "@value": "",
                },
                "Property Domain": "terminusdb:///schema#Journey",
                "Property ID": "terminusdb:///schema#Duration",
                "Property Name": {
                    "@type": "http://www.w3.org/2001/XMLSchema#string",
                    "@value": "",
                },
                "Property Range": "http://www.w3.org/2001/XMLSchema#integer",
                "Property Type": {
                    "@type": "http://www.w3.org/2001/XMLSchema#string",
                    "@value": "Data",
                },
            }
        ],
        "deletes": 0,
        "inserts": 0,
        "transaction_retry_count": 0,
    }


@pytest.fixture(scope="module")
def one_object():
    return {
        "@type": "api:WoqlResponse",
        "api:status": "api:success",
        "api:variable_names": ["Object ID", "Object Type"],
        "bindings": [
            {
                "Object ID": "terminusdb:///data/Journey_myobj",
                "Object Type": "terminusdb:///schema#Journey",
            }
        ],
        "deletes": 0,
        "inserts": 0,
        "transaction_retry_count": 0,
    }


@pytest.fixture(scope="module")
def one_prop_val():
    return {
        "@type": "api:WoqlResponse",
        "api:status": "api:success",
        "api:variable_names": [
            "Object ID",
            "Property ID",
            "Property Value",
            "Value ID",
            "Value Class",
        ],
        "bindings": [
            {
                "Object ID": "terminusdb:///data/Journey_myobj",
                "Property ID": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
                "Property Value": "terminusdb:///schema#Journey",
                "Value Class": "system:unknown",
                "Value ID": "system:unknown",
            },
            {
                "Object ID": "terminusdb:///data/Journey_myobj",
                "Property ID": "terminusdb:///schema#Duration",
                "Property Value": {
                    "@type": "http://www.w3.org/2001/XMLSchema#integer",
                    "@value": 75,
                },
                "Value Class": "system:unknown",
                "Value ID": "system:unknown",
            },
        ],
        "deletes": 0,
        "inserts": 0,
        "transaction_retry_count": 0,
    }
