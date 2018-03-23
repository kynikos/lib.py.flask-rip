from setuptools import setup

setup(
    # Flask-RIP is already taken
    name='flask-restinpeace',
    version='1.0.1',
    description=('Create Flask REST APIs in peace.'),
    long_description=('Create Flask REST APIs in peace.'),
    url='https://github.com/kynikos/lib.py.flask-rip',
    author='Dario Giovannetti',
    author_email='dev@dariogiovannetti.net',
    license='GPLv3+',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Web Environment',
        'Framework :: Flask',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',  # noqa
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Topic :: Internet :: WWW/HTTP :: WSGI :: Middleware',  # noqa
    ],
    keywords='flask rest restful api marshal marshmallow',
    py_modules=["flask_rip"],
)
