from setuptools import setup, find_packages

with open("README.rst") as f:
    readme = f.read()
with open("LICENSE.rst") as f:
    license = f.read()
with open("CHANGES.rst") as f:
    changes = f.read()

setup(
    name="jsonapi_client",
    version="1.0.0-dev",

    description="Comprehensive, yet easy-to-use, pythonic, ORM-like access to JSON API services",
    long_description=f"{readme}\n\n{license}\n\n{changes}",
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.6",
        "Topic :: Software Development :: Libraries",
        "License :: OSI Approved :: BSD License",
    ],
    author="Zoltan Papp",
    author_email="zoltan.papp@qvantel.com",
    url="https://github.com/qvantel/jsonapi-client",
    keywords="JSONAPI JSON API client",
    license="BSD-3",
    packages=find_packages(exclude=['contrib', 'docs', 'tests']),
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        "requests",
        "jsonschema",
        "aiohttp",
    ],
)
