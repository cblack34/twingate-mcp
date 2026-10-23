from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Page[T](BaseModel):
    items: list[T]
    total_returned: int
    truncated: bool


class User(BaseModel):
    id: str
    email: str | None
    first_name: str
    last_name: str
    role: str
    state: str


class Group(BaseModel):
    id: str
    name: str
    type: str
    is_active: bool
    member_count: int


class Resource(BaseModel):
    id: str
    name: str
    address: str
    remote_network: str
    is_active: bool


class RemoteNetwork(BaseModel):
    id: str
    name: str
    location: str
    is_active: bool
    connector_count: int


class Connector(BaseModel):
    id: str
    name: str
    remote_network: str
    state: str
    last_heartbeat_at: datetime | None


class Device(BaseModel):
    id: str
    name: str | None
    os_name: str | None
    user_email: str | None
    is_trusted: bool
    last_seen_at: datetime | None


class NamedRef(BaseModel):
    id: str
    name: str


class Principal(NamedRef):
    type: Literal["group", "service_account"]


class ResourceAccess(BaseModel):
    resource: NamedRef
    principals: list[Principal]
    truncated: bool


class UserAccess(BaseModel):
    email: str
    groups: list[NamedRef]
    resources: list[NamedRef]
    truncated: bool
