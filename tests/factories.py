import base64

from faker import Faker
from polyfactory import Use
from polyfactory.factories.pydantic_factory import ModelFactory
from pydantic import BaseModel

from twingate_mcp.models import (
    Connector,
    Device,
    Group,
    NamedRef,
    Principal,
    RemoteNetwork,
    Resource,
    ResourceAccess,
    User,
    UserAccess,
)

SEED = 20261022
FAKE_NETWORKS = ("acme-test", "example-net")
FAKER = Faker()
FAKER.seed_instance(SEED)


def node_id(kind: str) -> str:
    return base64.b64encode(f"{kind}:{FAKER.random_int(1, 99999)}".encode()).decode()


def fake_network() -> str:
    return FAKER.random_element(FAKE_NETWORKS)


class _Base[T: BaseModel](ModelFactory[T]):
    __is_base_factory__ = True
    __faker__ = FAKER
    __random_seed__ = SEED


class UserFactory(_Base[User]):
    id = Use(node_id, "User")
    email = Use(FAKER.safe_email)
    first_name = Use(FAKER.first_name)
    last_name = Use(FAKER.last_name)
    role = Use(FAKER.random_element, ("ADMIN", "DEVOPS", "SUPPORT", "MEMBER"))
    state = Use(FAKER.random_element, ("ACTIVE", "DISABLED", "PENDING"))


class GroupFactory(_Base[Group]):
    id = Use(node_id, "Group")
    name = Use(lambda: f"{FAKER.word()}-team")
    type = Use(FAKER.random_element, ("MANUAL", "SYNCED", "SYSTEM"))


class ResourceFactory(_Base[Resource]):
    id = Use(node_id, "Resource")
    name = Use(lambda: f"{FAKER.word()}-service")
    address = Use(FAKER.safe_domain_name)
    remote_network = Use(fake_network)


class RemoteNetworkFactory(_Base[RemoteNetwork]):
    id = Use(node_id, "RemoteNetwork")
    name = Use(fake_network)
    location = Use(FAKER.random_element, ("AWS", "AZURE", "GOOGLE_CLOUD", "ON_PREMISE", "OTHER"))


class ConnectorFactory(_Base[Connector]):
    id = Use(node_id, "Connector")
    name = Use(lambda: f"{FAKER.word()}-connector")
    remote_network = Use(fake_network)
    state = Use(FAKER.random_element, ("ALIVE", "DEAD_NO_HEARTBEAT"))


class DeviceFactory(_Base[Device]):
    id = Use(node_id, "Device")
    name = Use(lambda: f"laptop-{FAKER.random_int(1, 999)}")
    os_name = Use(FAKER.random_element, ("MAC_OS", "WINDOWS", "LINUX", "IOS", "ANDROID"))
    user_email = Use(FAKER.safe_email)


class NamedRefFactory(_Base[NamedRef]):
    id = Use(node_id, "Group")
    name = Use(lambda: f"{FAKER.word()}-team")


class PrincipalFactory(_Base[Principal]):
    id = Use(node_id, "Group")
    name = Use(lambda: f"{FAKER.word()}-team")


class ResourceAccessFactory(_Base[ResourceAccess]):
    resource = Use(NamedRefFactory.build)
    principals = Use(PrincipalFactory.batch, 3)


class UserAccessFactory(_Base[UserAccess]):
    email = Use(FAKER.safe_email)
    groups = Use(NamedRefFactory.batch, 2)
    resources = Use(NamedRefFactory.batch, 3)
