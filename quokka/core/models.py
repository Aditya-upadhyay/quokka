#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import datetime
import random
from flask import url_for, current_app
from flask.ext.security import current_user
from flask.ext.admin.babel import lazy_gettext
from quokka.core.db import db
from quokka import admin
from quokka.core.admin.models import ModelAdmin
from quokka.modules.accounts.models import User
from quokka.utils.text import slugify

logger = logging.getLogger()


###############################################################
# Commom extendable base classes
###############################################################


class Publishable(object):
    published = db.BooleanField(default=False)
    available_at = db.DateTimeField(default=datetime.datetime.now)
    created_at = db.DateTimeField(default=datetime.datetime.now)
    updated_at = db.DateTimeField(default=datetime.datetime.now)
    created_by = db.ReferenceField(User)
    last_updated_by = db.ReferenceField(User)

    def save(self, *args, **kwargs):
        self.updated_at = datetime.datetime.now()

        try:
            user = User.objects.get(id=current_user.id)
            if not self.id:
                self.created_by = user
            self.last_updated_by = user
        except Exception as e:
            logger.warning("No user to save the model: %s" % e.message)

        super(Publishable, self).save(*args, **kwargs)


class Slugged(object):
    slug = db.StringField(max_length=255)
    long_slug = db.StringField()
    mpath = db.StringField()

    def _create_mpath_long_slug(self):
        try:
            if self.parent and self.parent != self:
                self.long_slug = "/".join(
                    [self.parent.long_slug, self.slug]
                )

                self.mpath = "".join(
                    [self.parent.mpath, self.slug, ',']
                )
            else:
                self.long_slug = self.slug
                self.mpath = ",%s," % self.slug
        except:
            logger.info("excepting to content validate_long_slug")
            self.long_slug = "/".join(
                [self.channel.long_slug, self.slug]
            )

            self.mpath = "".join([self.channel.mpath, self.slug, ','])

    def validate_long_slug(self):

        self._create_mpath_long_slug()

        filters = dict(long_slug=self.long_slug)
        if self.id:
            filters['id__ne'] = self.id

        exist = self.__class__.objects(**filters)
        if exist.count():
            if current_app.config.get('SMART_SLUG_ENABLED', False):
                self.slug = "{}-{}".format(self.slug, random.getrandbits(32))
                self._create_mpath_long_slug()
            else:
                raise db.ValidationError(
                    lazy_gettext("%(slug)s slug already exists",
                                 slug=self.long_slug)
                )

    def validate_slug(self, title=None):
        if self.slug:
            self.slug = slugify(self.slug)
        else:
            self.slug = slugify(title or self.title)


class Comment(Publishable, db.EmbeddedDocument):
    body = db.StringField(verbose_name="Comment", required=True)
    author = db.StringField(verbose_name="Name", max_length=255, required=True)
    published = db.BooleanField(default=True)

    def __unicode__(self):
        return "{}-{}...".format(self.author, self.body[:10])

    meta = {
        'indexes': ['-created_at', '-available_at'],
        'ordering': ['-created_at']
    }


class Commentable(object):
    comments = db.ListField(db.EmbeddedDocumentField(Comment))


class Imaged(object):
    main_image = db.ImageField(thumbnail_size=(100, 100, True))
    main_image_caption = db.StringField()


class Tagged(object):
    """TODO: implement tags"""
    pass


class Channel(Publishable, Slugged, db.DynamicDocument):
    title = db.StringField(max_length=255, required=True)
    description = db.StringField()
    show_in_menu = db.BooleanField(default=False)
    is_homepage = db.BooleanField(default=False)
    include_in_rss = db.BooleanField(default=False)
    indexable = db.BooleanField(default=True)
    canonical_url = db.StringField()
    order = db.IntField(default=0)

    # MPTT
    parent = db.ReferenceField('self', required=False, default=None)

    @classmethod
    def get_homepage(cls, attr=None):
        try:
            homepage = cls.objects.get(is_homepage=True)
        except Exception, e:
            logger.info("There is no homepage: %s" % e.message)
            return None
        else:
            if not attr:
                return homepage
            else:
                return getattr(homepage, attr, homepage)

    def __unicode__(self):
        return "{}-{}".format(self.title, self.long_slug)

    def clean(self):
        homepage = Channel.objects(is_homepage=True)
        if self.is_homepage and homepage and not self in homepage:
            raise db.ValidationError(lazy_gettext(u"Home page already exists"))
        super(Channel, self).clean()

    def save(self, *args, **kwargs):

        self.validate_slug()
        self.validate_long_slug()

        super(Channel, self).save(*args, **kwargs)


class Channeling(object):
    channel = db.ReferenceField(Channel, required=True)
    # Objects can be in only one main channel it gives an url
    # but the objects can also be relates to other channels
    channels = db.ListField(db.ReferenceField('Channel'))
    show_on_channel = db.BooleanField(default=True)


###############################################################
# Base Content for every new content to extend. inheritance=True
###############################################################

class Content(Imaged, Publishable, Slugged, Commentable, Channeling,
              db.DynamicDocument):
    title = db.StringField(max_length=255, required=True)
    summary = db.StringField(required=False)

    meta = {
        'allow_inheritance': True,
        'indexes': ['-created_at', 'slug'],
        'ordering': ['-created_at']
    }

    def get_absolute_url(self):
        if self.channel.is_homepage:
            long_slug = self.slug
        else:
            long_slug = self.long_slug

        try:
            return url_for(self.URL_NAMESPACE, long_slug=long_slug)
        except:
            return url_for('.detail', long_slug=long_slug)

    def __unicode__(self):
        return self.title

    @property
    def content_type(self):
        return self.__class__.__name__

    def save(self, *args, **kwargs):

        self.validate_slug()
        self.validate_long_slug()

        super(Content, self).save(*args, **kwargs)


class ConfigValue(db.EmbeddedDocument):
    FORMATS = (
        ('json', "json"),
        ('text', "text"),
        ('int', "int"),
        ('float', "float"),
    )
    key = db.StringField(max_length=255)
    value = db.StringField()
    format = db.StringField(choices=FORMATS)


class Config(Publishable, db.DynamicDocument):
    group = db.StringField(max_length=255)
    description = db.StringField()
    values = db.ListField(db.EmbeddedDocumentField(ConfigValue))


###############################################################
# Admin views
###############################################################

class ConfigAdmin(ModelAdmin):
    roles_accepted = ('admin', 'developer')
    column_list = ("group", "description", "published",
                   "created_at", "updated_at")
    column_filters = ("group", "description")
    form_columns = ("group", "description", "published", "values")

admin.register(Config, ConfigAdmin, category="Settings")


class ChannelAdmin(ModelAdmin):
    roles_accepted = ('admin', 'editor')
    column_list = ('title', 'long_slug', 'is_homepage', 'published')
    column_filters = ['published', 'is_homepage', 'include_in_rss',
                      'show_in_menu', 'indexable']
    column_searchable_list = ('title', 'description')
    form_columns = ['title', 'slug', 'description', 'parent', 'is_homepage',
                    'include_in_rss', 'indexable', 'show_in_menu', 'order',
                    'published', 'canonical_url']


admin.register(Channel, ChannelAdmin, category="Content")
