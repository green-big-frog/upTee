Setting up a development server
===============================
Setting up a development server is important if you want to help with the development of upTee.

Installation
------------
###Install all requirements    
Be sure to install all requirements shown in the [README](https://github.com/upTee/upTee/blob/master/README.md).    
In case the command _pip_ is not available after installing _setuptools_ run the following command:    
```shell
$ easy_install pip
```
Switch into the uptee directory and run the following command:    
```shell
$ pip install -r requirements.txt
```
If an error appears install the missing packages. The error messages are obvious.    
In windows download packages which fails from [here](http://www.lfd.uci.edu/~gohlke/pythonlibs/).
Repeat the command until the installation finishes successfully!    
If there are still problems with some modules have a look at the [Troubleshooting section](https://github.com/upTee/upTee/blob/master/docs/development_server.md#troubleshooting).

###Set up the project
Switch into the _uptee_ directory.    
To set up the project copy the _settings_local.py.example_ and rename the new file to _settings_local.py_.    
Now edit the settings how u like. You can find an example for a development server [here](https://github.com/upTee/upTee/blob/master/docs/settings_devlopment/settings_local.py).    
Copy _browscap.csv.example_ and rename the new file to _browscap.csv_.

###Install the database    
```shell
$ python manage.py syncdb
```
It will ask to create a Superuser. Do not do that!    
```shell
$ python manage.py migrate
```
Now create the Superuser.    
```shell
$ python manage.py createsuperuser
```

###Set up the port map
The port map is a list of available ports for the teeworlds servers. Be sure that the ports are not blocked by a firewall.    
```shell
$ python manage.py create_portmap 8300 8320
```
This command adds the ports 8300 till 8320 to upTee. Decide yourself which ports you want to use and how many you need.

###Start up the server
You will have to run two processes for starting up the Server.    
First you have to run the celery worker and celerybeat (start as background process or two sessions).    
```shell
$ python manage.py celery worker --loglevel=info
$ python manage.py celery beat
```
Be sure that the broker for celery is running (RabbitMQ is recommended).    
If the example _[settings_local.py](https://github.com/upTee/upTee/blob/master/docs/settings_devlopment/settings_local.py)_ is used the database will be used.    
After celery is running, run the server itself.
```shell
$ python manage.py runserver
```
The website is now available under __http://localhost:8000/__

Troubleshooting
---------------
###error: Unable to find vcvarsall.bat
Some modules need a C/C++ compiler to build parts of the module for performance reasons.    
In windows it may happen that it will not find the compiler or it might be even not installed.    
If this is the case just download module from [here](http://www.lfd.uci.edu/~gohlke/pythonlibs/) and install it. After the installation you may still get the same error.    
Just comment out the concerned module in the _requirements.txt_.    
Example:    
```
# PIL>=1.1.7
```
