from captcha.conf import settings as captcha_settings
from captcha.models import CaptchaStore
from django.core.mail import mail_admins, send_mail
from django.contrib.auth import logout as user_logout
from django.contrib.auth import login as user_login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.urlresolvers import reverse
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render_to_response
from django.template import RequestContext
from accounts.forms import *
from accounts.models import Activation
from settings import ADMINS, DEBUG, SERVER_EMAIL, TESTING_STATE
from testingstate.forms import TestingForm


@login_required
def logout(request):
    user_logout(request)
    messages.success(request, "Successfully logged out.")
    return redirect(request.REQUEST.get('next', reverse('home')))


def login(request):
    if request.user.is_authenticated():
        return redirect(reverse('home'))
    if request.method == 'POST':
        post = request.POST.copy()
        next = post.get('next', reverse('home'))
        form = AuthenticationForm(data=post)
        if form.is_valid():
            user_login(request, form.get_user())
            messages.success(request, "Successfully logged in.")
        else:
            messages.warning(request, "The combination of username and password is wrong or your account is not activated yet.")
        if next == reverse('logout') or next == reverse('logout')[:-1]:
            next = reverse('home')
        return redirect(next)
    return auth_views.login(request, 'accounts/login.html')


@login_required
def settings(request):
    user_form = SettingsUserForm(instance=request.user)
    profile_form = SettingsUserprofileForm(instance=request.user.profile)
    if request.method == 'POST':
        user_form = SettingsUserForm(request.POST, instance=request.user)
        profile_form = SettingsUserprofileForm(request.POST, instance=request.user.profile)
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, "Your profile was saved successfully")
    return render_to_response('accounts/settings.html', {
            'user_form': user_form,
            'profile_form': profile_form,
        }, context_instance=RequestContext(request))


@login_required
def change_password(request):
    form = PasswordChangeForm(current_user=request.user)
    if request.method == 'POST':
        form = PasswordChangeForm(request.POST, current_user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, u'Password changed successfully.')
    return render_to_response('accounts/password_change.html', {
            'form': form,
        }, context_instance=RequestContext(request))


def password_recover(request, recover_key=None):
    if request.user.is_authenticated() or not SERVER_EMAIL:
        raise Http404
    if not recover_key:
        form = RecoverPasswordForm()
        if request.method == 'POST':
            form = RecoverPasswordForm(request.POST)
            if form.is_valid():
                user = User.objects.get(username=form.cleaned_data['username'])
                messages.success(request, "An email has been sent to your email address with further instructions.")
                key = User.objects.make_random_password(length=32)
                activation = Activation(user=user, key=key)
                activation.save()
                send_mail('upTee password recover', "The password recovery function was used for your account. If you didn't do that just ignore this email.\r\n\r\nPlease click the following link to reset your password:\r\nhttp://{0}/recoverpassword/{1}\r\n\r\nAnother mail will be sent with your new password.".format(request.META['HTTP_HOST'], key), SERVER_EMAIL, [user.email], fail_silently=not DEBUG)
                return redirect(reverse('home'))
        return render_to_response('accounts/password_recover.html', {
                'form': form,
            }, context_instance=RequestContext(request))
    recovery = get_object_or_404(Activation.objects.select_related(), key=recover_key)
    key = User.objects.make_random_password(length=12)
    recovery.user.password = make_password(key)
    recovery.user.save()
    recovery.delete()
    messages.success(request, "An email has been sent to your email address with your new password.")
    send_mail('upTee password recover', "The password recovery function was used for your account.\r\n\r\nYour new password is: {0}".format(key), SERVER_EMAIL, [recovery.user.email], fail_silently=not DEBUG)
    return redirect(reverse('home'))


def username_recover(request):
    if request.user.is_authenticated():
        raise Http404
    form = RecoverUsernameForm()
    if request.method == 'POST':
        form = RecoverUsernameForm(request.POST)
        if form.is_valid():
            user = User.objects.get(email=form.cleaned_data['email'])
            messages.success(request, "An email has been sent to your email address with your username.")
            send_mail('upTee username recover', "The username recovery function was used for your account.\r\n\r\nYour username is: {0}".format(user.username), SERVER_EMAIL, [user.email], fail_silently=not DEBUG)
            return redirect(reverse('home'))
    return render_to_response('accounts/username_recover.html', {
            'form': form,
        }, context_instance=RequestContext(request))


def register(request):
    if request.user.is_authenticated():
        return redirect(reverse('home'))
    if request.method == 'POST':
        register_form = RegisterForm(request.POST)
        testing_form = TestingForm(request.POST) if TESTING_STATE else None
        if register_form.is_valid() and (not testing_form or testing_form.is_valid()):
            testing_form.save()
            new_user = User(
                username=register_form.cleaned_data['username'],
                email=register_form.cleaned_data['email'],
                password=make_password(register_form.cleaned_data['password1']),
                is_active=False,
            )
            new_user.save()
            if SERVER_EMAIL:
                messages.success(request, "Your account was successfully created. An activation link has been sent to your email address.")
                key = User.objects.make_random_password(length=32)
                activation = Activation(user=new_user, key=key)
                activation.save()
                send_mail('upTee registration', 'Thank you for your registration.\r\nClick the link below to activate your account:\r\n\r\nhttp://{0}/activate/{1}'.format(request.META['HTTP_HOST'], key), SERVER_EMAIL, [new_user.email], fail_silently=not DEBUG)
            else:
                messages.success(request, "Your account was successfully created. An Admin should contact you shortly.")
            if ADMINS:
                mail_admins('User registration', u'The following user just registered and wants to be activated:\r\n\r\n{0}'.format(register_form.cleaned_data['username']), fail_silently=not DEBUG)
            return redirect(reverse('home'))
    else:
        register_form = RegisterForm()
        testing_form = TestingForm() if TESTING_STATE else None
    challenge, response = captcha_settings.get_challenge()()
    store = CaptchaStore.objects.create(challenge=challenge, response=response)
    key = store.hashkey
    return render_to_response('accounts/register.html', {
            'captcha': key,
            'register_form': register_form,
            'testing_form': testing_form,
        }, context_instance=RequestContext(request))


def activate(request, activation_key):
    if request.user.is_authenticated():
        raise Http404
    activation = get_object_or_404(Activation.objects.select_related(), key=activation_key)
    activation.user.is_active = True
    activation.user.save()
    activation.delete()
    return render_to_response('accounts/activate.html', context_instance=RequestContext(request))


def users(request):
    users = User.objects.select_related().filter(is_active=True).order_by('username')
    return render_to_response('accounts/users.html', {
            'users': users,
        }, context_instance=RequestContext(request))


def user(request, user_id):
    user = get_object_or_404(User.objects.select_related(), pk=user_id)
    return render_to_response('accounts/user_profile.html', {
            'user_profile': user,
        }, context_instance=RequestContext(request))
