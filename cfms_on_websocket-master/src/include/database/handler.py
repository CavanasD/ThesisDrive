__all__ = ["engine", "Session", "Base"]

from sqlalchemy import URL, create_engine, event
from sqlalchemy.orm import (
    DeclarativeBase,
    ORMExecuteState,
    sessionmaker,
    with_loader_criteria,
)

from include.classes.enum.status import EntityStatus
from include.conf_loader import global_config
from include.constants import DEFAULT_TOKEN_EXPIRY_SECONDS

SUPPORTED_DB_TYPES = {
    "mysql": "mysql+mysqlconnector",
    "postgresql": "postgresql+psycopg2",
    "sqlite": "sqlite",
}


debug_enabled = global_config["debug"]

db_type = global_config["database"]["type"]
drivername = SUPPORTED_DB_TYPES.get(db_type)
if not drivername:
    raise ValueError(f"Unsupported database type: {db_type}")

if db_type == "sqlite":
    db_file = global_config["database"]["file"]
    engine = create_engine(f"sqlite:///{db_file}", echo=debug_enabled)
else:
    username = global_config["database"]["username"]
    password = global_config["database"]["password"]
    host = global_config["database"]["host"]
    port = global_config["database"]["port"]
    db_name = global_config["database"]["name"]

    url = URL.create(
        drivername=drivername,
        username=username,
        password=password,
        host=host,
        port=port,
        database=db_name,
    )
    engine = create_engine(
        url,
        pool_recycle=DEFAULT_TOKEN_EXPIRY_SECONDS,
        echo=debug_enabled,
    )

Session = sessionmaker(bind=engine)


@event.listens_for(Session, "do_orm_execute")
def _add_filtering_criteria(execute_state: ORMExecuteState) -> None:
    if (
        execute_state.is_select
        and not execute_state.is_column_load
        and not execute_state.execution_options.get("include_deleted", False)
    ):
        from include.database.models.entity import Folder, Document

        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                Folder, lambda cls: cls.status != EntityStatus.DELETED
            ),
            with_loader_criteria(
                Document, lambda cls: cls.status != EntityStatus.DELETED
            ),
        )


class Base(DeclarativeBase):
    pass


Base.metadata.naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
