import nox.sessions

# Nox
nox.options.reuse_existing_virtualenvs = True
nox.options.sessions = [
    'tests',
    'tests_sqlalchemy',
    'tests_graphql',
    'tests_fastapi',
]

# Versions
PYTHON_VERSIONS = ['3.9']
SQLALCHEMY_VERSIONS = [
    *(f'1.3.{x}' for x in range(7, 1 + 24)),
    *(f'1.4.{x}' for x in range(14, 1 + 23)),
]
GRAPHQL_CORE_VERSIONS = [
    *(f'3.1.{x}' for x in range(3, 1 + 6)),
]
FASTAPI_VERSIONS = [
    '0.51.0', '0.52.0', '0.53.2', '0.54.2', '0.56.1', '0.56.1', '0.57.0', '0.58.1', '0.59.0',
    '0.60.2', '0.61.2', '0.62.0', '0.63.0', '0.64.0', '0.65.3', '0.66.1', '0.67.0', '0.68.1',
]


@nox.session(python=PYTHON_VERSIONS)
def tests(session: nox.sessions.Session, *, overrides: dict[str, str] = {}):
    """ Run all tests """
    # session.install(*requirements(overrides), '.')

    session.install('poetry')
    session.run('poetry', 'install')
    if overrides:
        session.install(*(f'{name}=={version}' for name, version in overrides.items()))

    # Test
    session.run('pytest', 'tests/', '--ignore=tests/test_mypy.py', '--cov=jessiql')


@nox.session(python=PYTHON_VERSIONS[-1])
@nox.parametrize('sqlalchemy', SQLALCHEMY_VERSIONS)
def tests_sqlalchemy(session: nox.sessions.Session, sqlalchemy):
    """ Test against a specific SqlAlchemy version """
    tests(session, overrides={'sqlalchemy': sqlalchemy})


@nox.session(python=PYTHON_VERSIONS[-1])
@nox.parametrize('graphql_core', GRAPHQL_CORE_VERSIONS)
def tests_graphql(session: nox.sessions.Session, graphql_core):
    """ Test against a specific GraphQL version """
    tests(session, overrides={'graphql-core': graphql_core})


@nox.session(python=PYTHON_VERSIONS[-1])
@nox.parametrize('fastapi', FASTAPI_VERSIONS)
def tests_fastapi(session: nox.sessions.Session, fastapi):
    """ Test against a specific FastAPI version """
    tests(session, overrides={'fastapi': fastapi})



# Get requirements.txt from poetry
import tempfile, subprocess
with tempfile.NamedTemporaryFile('w+') as f:
    subprocess.run(f'poetry export --no-interaction --dev --format requirements.txt --without-hashes --output={f.name}', shell=True, check=True)
    f.seek(0)
    requirements_txt = f.readlines()

def requirements(overrides: dict[str, str]) -> list[str]:
    # Filter requirements (to avoid conflicting requirements)
    requirements = [
        line.split(';', 1)[0]  # Example: "sqlalchemy==1.4.23; (python_version >= "2.7" and python_full_version < "3.0.0") or (python_full_version >= "3.6.0")"
        for line in requirements_txt
        if not any(line.startswith(f'{override}==') for override in overrides)
    ]
    # Merge with overrides
    return [
        *requirements,
        *[f'{name}=={version}' for name, version in overrides.items()]
    ]
