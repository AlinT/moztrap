# Case Conductor is a Test Case Management system.
# Copyright (C) 2011 uTest Inc.
#
# This file is part of Case Conductor.
#
# Case Conductor is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Case Conductor is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Case Conductor.  If not, see <http://www.gnu.org/licenses/>.
"""
Models for test execution (runs, results).

"""
import datetime

from django.core.exceptions import ValidationError
from django.db import models

from django.contrib.auth.models import User

from model_utils import Choices

from ..core.ccmodel import CCModel, TeamModel, utcnow
from ..core.models import ProductVersion
from ..environments.models import Environment, HasEnvironmentsModel
from ..library.models import CaseVersion, Suite, CaseStep, SuiteCase



class Run(TeamModel, HasEnvironmentsModel):
    """A test run."""
    STATUS = Choices("draft", "active", "disabled")

    productversion = models.ForeignKey(ProductVersion, related_name="runs")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=30, db_index=True, choices=STATUS, default=STATUS.draft)
    start = models.DateField(default=datetime.date.today)
    end = models.DateField(blank=True, null=True)

    caseversions = models.ManyToManyField(
        CaseVersion, through="RunCaseVersion", related_name="runs")
    suites = models.ManyToManyField(
        Suite, through="RunSuite", related_name="runs")


    def __unicode__(self):
        """Return unicode representation."""
        return self.name


    def clean(self):
        """Validate instance field values."""
        if self.end is not None and self.start > self.end:
            raise ValidationError("Start date must be prior to end date.")


    class Meta:
        permissions = [("manage_runs", "Can add/edit/delete test runs.")]


    @property
    def parent(self):
        return self.productversion


    @classmethod
    def cascade_envs_to(cls, objs, adding):
        if adding:
            return {}
        return {RunCaseVersion: RunCaseVersion.objects.filter(run__in=objs)}


    def clone(self, *args, **kwargs):
        """Clone this Run with default cascade behavior."""
        kwargs.setdefault(
            "cascade", ["runcaseversions", "runsuites", "environments", "team"])
        return super(Run, self).clone(*args, **kwargs)


    def activate(self):
        """Make run active, locking in runcaseversions for all suites."""
        if self.status == self.STATUS.draft:
            self._lock_case_versions()
        self.status = self.STATUS.active
        self.save(force_update=True)


    def _lock_case_versions(self):
        """Select caseversions from suites, create runcaseversions."""
        order = 1
        for runsuite in RunSuite.objects.filter(
                run=self).order_by("order").select_related("suite"):
            for suitecase in SuiteCase.objects.filter(
                    suite=runsuite.suite).order_by(
                    "order").select_related("case"):
                try:
                    caseversion = suitecase.case.versions.filter(
                        productversion=self.productversion,
                        status=CaseVersion.STATUS.active).get()
                except CaseVersion.DoesNotExist:
                    pass
                else:
                    rcv = RunCaseVersion(
                        run=self, caseversion=caseversion, order=order)
                    envs = rcv._inherited_environment_ids
                    if envs:
                        rcv.save(force_insert=True, inherit_envs=False)
                        rcv.environments.add(*envs)
                        order += 1



class RunCaseVersion(HasEnvironmentsModel, CCModel):
    """An ordered association between a Run and a CaseVersion."""
    run = models.ForeignKey(Run, related_name="runcaseversions")
    caseversion = models.ForeignKey(CaseVersion, related_name="runcaseversions")
    order = models.IntegerField(default=0, db_index=True)


    def __unicode__(self):
        """Return unicode representation."""
        return "Case '%s' included in run '%s'" % (self.caseversion, self.run)


    def bug_urls(self):
        """Returns set of bug URLs associated with this run/caseversion."""
        return set(
            StepResult.objects.filter(
                result__runcaseversion=self).exclude(
                bug_url="").values_list("bug_url", flat=True).distinct()
            )


    class Meta:
        ordering = ["order"]
        permissions = [
            ("execute", "Can run tests and report results."),
            ]


    @property
    def _inherited_environment_ids(self):
        """Intersection of run/caseversion environment IDs."""
        run_env_ids = set(
            self.run.environments.values_list("id", flat=True))
        case_env_ids = set(
            self.caseversion.environments.values_list("id", flat=True))
        return run_env_ids.intersection(case_env_ids)


    def save(self, *args, **kwargs):
        """
        Save instance; new instances get intersection of run/case environments.

        """
        adding = False
        if self.id is None:
            adding = True
        inherit_envs = kwargs.pop("inherit_envs", True)

        ret = super(RunCaseVersion, self).save(*args, **kwargs)

        if adding and inherit_envs:
            self.environments.add(*self._inherited_environment_ids)

        return ret



class RunSuite(CCModel):
    """An ordered association between a Run and a Suite."""
    run = models.ForeignKey(Run, related_name="runsuites")
    suite = models.ForeignKey(Suite, related_name="runsuites")
    order = models.IntegerField(default=0, db_index=True)


    def __unicode__(self):
        """Return unicode representation."""
        return "Suite '%s' included in run '%s'" % (self.suite, self.run)


    class Meta:
        ordering = ["order"]



class Result(CCModel):
    """A result of a User running a RunCaseVersion in an Environment."""
    STATUS = Choices("assigned", "started", "passed", "failed", "invalidated")
    REVIEW = Choices("pending", "reviewed")

    tester = models.ForeignKey(User, related_name="results")
    runcaseversion = models.ForeignKey(
        RunCaseVersion, related_name="results")
    environment = models.ForeignKey(Environment, related_name="results")
    status = models.CharField(
        max_length=50, db_index=True, choices=STATUS, default=STATUS.assigned)
    started = models.DateTimeField(default=utcnow)
    completed = models.DateTimeField(blank=True, null=True)
    comment = models.TextField(blank=True)

    review = models.CharField(
        max_length=50, db_index=True, choices=REVIEW, default=REVIEW.pending)
    reviewed_on = models.DateTimeField(blank=True, null=True)
    reviewed_by = models.ForeignKey(
        User, related_name="reviews", blank=True, null=True)


    def __unicode__(self):
        """Return unicode representation."""
        return "%s, run by %s in %s: %s" % (
            self.runcaseversion, self.tester, self.environment, self.status)


    class Meta:
        permissions = [("review_results", "Can review/edit test results.")]


    def bug_urls(self):
        """Returns set of bug URLs associated with this result."""
        return set(
            self.stepresults.exclude(
                bug_url="").values_list("bug_url", flat=True).distinct()
            )



class StepResult(CCModel):
    """A result of a particular step in a test case."""
    STATUS = Choices("passed", "failed", "invalidated")

    result = models.ForeignKey(Result, related_name="stepresults")
    step = models.ForeignKey(CaseStep, related_name="stepresults")
    status = models.CharField(
        max_length=50, db_index=True, choices=STATUS, default=STATUS.passed)
    bug_url = models.URLField(blank=True)


    def __unicode__(self):
        """Return unicode representation."""
        return "%s (%s: %s)" % (self.result, self.step, self.status)
