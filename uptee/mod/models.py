import mimetypes
import os
import psutil
import signal
from datetime import timedelta
from markdown import markdown
from shutil import copyfile, rmtree
from celery import current_app as celery
from django.db import models
from django.contrib.auth.models import User
from django.forms import ValidationError
from django.utils import timezone
from django.utils.html import escape
from picklefield.fields import PickledObjectField
from mod.templatetags.get_option import get_option
from settings import DEBUG, MEDIA_ROOT
from lib.twconfig import Config as TwConfig
from lib.twserverinfo import ServerInfo


class FreePortManager(models.Manager):
    def get_query_set(self):
        return super(FreePortManager, self).get_query_set().filter(is_active=False)


class ActiveServerManager(models.Manager):
    def get_query_set(self):
        return super(ActiveServerManager, self).get_query_set().filter(is_active=True)


class Mod(models.Model):
    mod_file = models.FileField(upload_to='uploads', help_text='Should be .zip or .tar')
    upload_date = models.DateTimeField('Upload date', auto_now=True)
    title = models.CharField(blank=False, max_length=100)
    mimetype = models.CharField(editable=False, max_length=100)

    class Meta:
        ordering = ['upload_date', 'title']

    def __unicode__(self):
        return self.title

    def save(self):
        self.mimetype = mimetypes.guess_type(self.mod_file.path)[0]
        super(Mod, self).save()

    def delete(self):
        if os.path.exists(self.mod_file.path):
            os.remove(self.mod_file.path)
        path = os.path.join(MEDIA_ROOT, 'mods', self.title)
        if os.path.exists(path):
            rmtree(path)
        super(Mod, self).delete()


class Port(models.Model):
    port = models.IntegerField(unique=True)
    is_active = models.BooleanField(default=False)

    objects = models.Manager()
    free = FreePortManager()

    @staticmethod
    def get_free_port():
        try:
            return Port.free.all()[0]
        except:
            return None

    class Meta:
        ordering = ['port']

    def __unicode__(self):
        return str(self.port)

    def validate_unique(self, exclude=None):
        if self.port < 0 or self.port > 65535:
            raise ValidationError('The used Port is out of range.')
        super(Port, self).validate_unique(exclude=exclude)

    def save(self):
        self.full_clean()
        super(Port, self).save()


class Server(models.Model):
    owner = models.ForeignKey(User, related_name='servers')
    mod = models.ForeignKey(Mod, related_name='servers')
    pid = models.IntegerField(blank=True, null=True, unique=True)
    port = models.OneToOneField(Port, blank=True, null=True, related_name='server')
    is_active = models.BooleanField(default=False)
    online = models.BooleanField(default=False)
    set_online_at = models.DateTimeField(auto_now=True)
    locked = models.BooleanField(default=False)
    automatic_restart = models.BooleanField(default=False)
    map_download_allowed = models.BooleanField(default=True)
    description = models.TextField(blank=True, help_text='You may use markdown')
    description_html = models.TextField(blank=True)
    server_info = PickledObjectField(blank=True, null=True)
    random_key = models.CharField(max_length=24, unique=True, null=True)

    objects = models.Manager()
    active = ActiveServerManager()

    @property
    def is_online(self):
        if self.port and self.port.is_active and self.online:
            return True
        return False

    def get_server_info(self):
        if self.is_online:
            s = ServerInfo()
            s.send(self.port.port)
            if not s.server_info and timezone.now() >= self.set_online_at + timedelta(seconds=10):  # assume there is something wrong with the server
                self.set_offline()
            info_dict = s.server_info
            info_dict['password'] = s.password
            self.server_info = info_dict
        else:
            self.server_info = ''
        self.save()

    @property
    def map_exists(self):
        if self.is_online:  # return true if server is online
            return True
        map_name = self.config_options.get(command='sv_map').value
        if self.maps.filter(name=map_name):
            return True
        return False

    class Meta:
        ordering = ['owner', 'mod', 'port']

    def __unicode__(self):
        return '{0} ({1}) Owner: {2}'.format(self.mod.title, self.is_online, self.owner.username)

    def check_online(self):
        if self.pid in psutil.get_pid_list():
            if not self.online:
                self.online = True
                self.save()
            return True
        self.set_offline()
        return False

    def set_offline(self):
        if self.port and self.port.is_active:
            self.port.is_active = False
            self.port.save()
            self.port = None
        if self.pid in psutil.get_pid_list():
            os.kill(self.pid, signal.SIGTERM)
        self.pid = None
        self.online = False
        self.server_info = ''
        self.save()

    def set_online(self):
        if not self.locked:
            ports = Port.objects.filter(server=self)
            if ports:
                for port in ports:
                    server = port.server
                    server.set_offline()
            self.port = Port.get_free_port()
            self.port.is_active = True
            self.port.save()
            if not DEBUG:  # don#t care for lock in debug mode
                self.locked = True
            self.set_online_at = timezone.now()
            self.save()
            path = os.path.join(MEDIA_ROOT, 'mods', self.mod.title)
            self.save_config()
            with open(os.path.join(path, 'storage.cfg'), 'w') as storage:
                storage.write('add_path servers/{0}/{1}/{2}\nadd_path $CURRENTDIR\n'.format(self.owner.username, self.id, self.random_key))
            from mod.tasks import run_server  # i dont like this
            run_server.delay(path, self)

    def save_config(self, download=False):
        path = os.path.join(MEDIA_ROOT, 'mods', self.mod.title)
        config = TwConfig(os.path.join(path, 'servers', self.owner.username, '{0}'.format(self.id), self.random_key, 'generated.cfg'))
        for option in self.config_options.all():
            if option.widget == Option.WIDGET_SELECT:
                value = option.value.split(',', 1)[0]
                widget = 'select:{0}'.format(option.value.split(',', 1)[1])
                config.add_option(option.command, value, widget)
            else:
                if download and option.widget == Option.WIDGET_PASSWORD:
                    config.add_option(option.command, '', option.get_widget_display())
                else:
                    config.add_option(option.command, option.value, option.get_widget_display())
        if download:
            config.add_option('sv_port', '8303')
        else:
            config.add_option('sv_port', self.port.port)
            config.add_option('ec_port', self.port.port)
            config.add_option('ec_password', 'uptee')
        for tune in self.config_tunes.all():
            config.add_tune(tune.command, tune.value)
        for vote in self.config_votes.all():
            config.add_vote(vote.command, vote.title)
        for rcon_command in self.config_rconcommands.all():
            config.add_rcon_command(rcon_command.command, rcon_command.value)
        config.write()

    def reset_settings(self, old_obj):
        for option in Option.objects.filter(server=self):
            option.delete()
        for tune in Tune.objects.filter(server=self):
            tune.delete()
        for vote in Vote.objects.filter(server=self):
            vote.delete()
        for rcon_command in RconCommand.objects.filter(server=self):
            rcon_command.delete()
        for available_rcon_command in AvailableRconCommand.objects.filter(server=self):
            available_rcon_command.delete()
        config_path = os.path.join(MEDIA_ROOT, 'mods', self.mod.title, 'config.cfg')
        config = TwConfig(config_path)
        config.read()
        for key, value in config.options.iteritems():
            widget = 1  # text
            for widget_type in Option.WIDGET_CHOICES:
                if widget_type[1] == value[1]:
                    widget = widget_type[0]
            data = Option(server=self, command=key, value=value[0], widget=widget)
            data.save()
        for tune in config.tunes:
            data = Tune(server=self, command=tune['command'], value=tune['value'])
            data.save()
        for vote in config.votes:
            data = Vote(server=self, command=vote['command'], title=vote['title'])
            data.save()
        for rcon_command in config.available_rcon_commands:
            data = AvailableRconCommand(server=self, command=rcon_command)
            data.save()
        # copy maps if there are already some
        if old_obj:
            server_maps_path = os.path.join(MEDIA_ROOT, 'mods', old_obj.mod.title, 'servers', old_obj.owner.username, '{0}'.format(old_obj.id), old_obj.random_key, 'maps')
            if os.path.exists(server_maps_path):
                maps = [_file for _file in os.listdir(server_maps_path) if os.path.splitext(_file)[1].lower() == '.map']
                for _map in maps:
                    new_server_maps_path = os.path.join(MEDIA_ROOT, 'mods', self.mod.title, 'servers', self.owner.username, '{0}'.format(self.id), self.random_key, 'maps')
                    if not os.path.exists(new_server_maps_path):
                        os.makedirs(new_server_maps_path)
                    copyfile(os.path.join(server_maps_path, _map), os.path.join(new_server_maps_path, _map))
                rmtree(os.path.join(MEDIA_ROOT, 'mods', old_obj.mod.title, 'servers', old_obj.owner.username))
        # copy default mod maps
        maps_path = os.path.join(MEDIA_ROOT, 'mods', self.mod.title, 'data', 'maps')
        if os.path.exists(maps_path):
            maps = [_file for _file in os.listdir(maps_path) if os.path.splitext(_file)[1].lower() == '.map']
            for _map in maps:
                map_obj = Map.objects.filter(server=self, name=os.path.splitext(_map)[0])
                if not map_obj:
                    map_obj = Map(server=self, name=os.path.splitext(_map)[0])
                    map_obj.save()
                    server_maps_path = os.path.join(MEDIA_ROOT, 'mods', self.mod.title, 'servers', self.owner.username, '{0}'.format(self.id), self.random_key, 'maps')
                    if not os.path.exists(server_maps_path):
                        os.makedirs(server_maps_path)
                    copyfile(os.path.join(maps_path, _map), os.path.join(server_maps_path, _map))

    def server_name(self):
        return get_option(self, 'sv_name')

    def save(self, *args, **kwargs):
        self.description_html = markdown(escape(self.description))
        super(Server, self).save(*args, **kwargs)

    def delete(self):
        self.set_offline()
        path = os.path.join(MEDIA_ROOT, 'mods', self.mod.title, 'servers', self.owner.username)
        if os.path.exists(path):
            rmtree(path)
        super(Server, self).delete()


class Config(models.Model):
    server = models.ForeignKey(Server, related_name='config_%(class)ss')
    command = models.CharField(max_length=100)

    class Meta:
        abstract = True


class Option(Config):
    value = models.CharField(blank=True, max_length=1000)

    WIDGET_TEXT = 1
    WIDGET_TEXTAREA = 2
    WIDGET_PASSWORD = 3
    WIDGET_CHECKBOX = 4
    WIDGET_SELECT = 5
    WIDGET_CHOICES = (
        (WIDGET_TEXT, 'text'),
        (WIDGET_TEXTAREA, 'textarea'),
        (WIDGET_PASSWORD, 'password'),
        (WIDGET_CHECKBOX, 'checkbox'),
        (WIDGET_SELECT, 'select'),
    )
    widget = models.IntegerField(choices=WIDGET_CHOICES, default=WIDGET_TEXT)

    def selections(self):
        if self.widget == Option.WIDGET_SELECT:
            return self.value.split(',')[1:]
        return None

    def get_value(self):
        if self.widget == Option.WIDGET_SELECT:
            return self.value.split(',')[0]
        return self.value

    class Meta:
        ordering = ['id']

    def __unicode__(self):
        return str(self.command)


class Tune(Config):
    value = models.FloatField()

    class Meta:
        ordering = ['id']

    def __unicode__(self):
        return str(self.command)


class Vote(Config):
    title = models.CharField(max_length=100)

    class Meta:
        ordering = ['id']

    def __unicode__(self):
        return str(self.command)


class RconCommand(Config):
    value = models.CharField(blank=True, max_length=500)

    class Meta:
        ordering = ['id']

    def __unicode__(self):
        return str(self.command)


class AvailableRconCommand(models.Model):
    server = models.ForeignKey(Server, related_name='config_available_rconcommands')
    command = command = models.CharField(max_length=100)

    class Meta:
        ordering = ['id']

    def __unicode__(self):
        return str(self.command)


class Map(models.Model):
    server = models.ForeignKey(Server, related_name="maps")
    name = models.CharField(max_length=100)
    author = models.CharField(max_length=100, blank=True)
    info = models.CharField(max_length=300, blank=True)
    download_count = models.IntegerField(default=0)

    class Meta:
        ordering = ['name']

    def get_download_url(self):
        path = os.path.join(MEDIA_ROOT, 'mods', self.server.mod.title, 'servers', self.server.owner.username, '{0}'.format(self.server.id), self.server.random_key, 'maps')
        if os.path.exists(path):
            for _file in os.listdir(path):
                if os.path.splitext(_file)[0] == self.name and os.path.splitext(_file)[1].lower() == '.map':
                    return os.path.join(path, _file)
        return None

    def delete(self):
        path = self.get_download_url()
        if path:
            os.remove(path)
        super(Map, self).delete()


class TaskEvent(models.Model):
    server = models.ForeignKey(Server, null=True, related_name="events")
    name = models.CharField(max_length=100)

    TYPE_START = 1
    TYPE_STOP = 2
    TYPE_RESTART = 3
    TYPE_CHOICES = (
        (TYPE_START, 'start'),
        (TYPE_STOP, 'stop'),
        (TYPE_RESTART, 'restart'),
    )
    task_type = models.IntegerField(choices=TYPE_CHOICES, default=TYPE_RESTART)
    date = models.DateTimeField()
    repeat = models.IntegerField(default=0, help_text='minutes for repeating the task (0 is no repeat)<br>day=1440, week=10080')

    STATUS_ACTIVE = 1
    STATUS_DONE = 2
    STATUS_ERROR = 3
    STATUS_CHOICES = (
        (STATUS_ACTIVE, 'active'),
        (STATUS_DONE, 'done'),
        (STATUS_ERROR, 'error'),
    )
    status = models.IntegerField(choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    task_id = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        ordering = ['date']

    def delete(self):
        celery.control.revoke(self.task_id)
        super(TaskEvent, self).delete()
