from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse

from ..core import sort, pagination, filters
from ..products.models import ProductList
from ..testexecution.models import TestCycleList, TestRunList
from ..users.decorators import login_redirect
from ..users.models import UserList

from .forms import TestCycleForm


def home(request):
    return redirect("manage_testcycles")



@login_redirect
def testcycles(request):
    if request.method == "POST":
        actions = [(k, v) for k, v in request.POST.iteritems()
                   if k.startswith("action-")]
        if actions:
            action, cycle_id = actions[0]
            action = action[len("action-"):]
            if action in ["activate", "deactivate", "delete", "clone"]:
                cycle = TestCycleList.get_by_id(cycle_id, auth=request.auth)
                try:
                    getattr(cycle, action)()
                except cycle.Conflict, e:
                    if e.response_error == "deleting.used.entity":
                        messages.error(
                            request,
                            'Cannot delete activated test cycle "%s."'
                            % cycle.name)
        return redirect(request.get_full_path())

    pagesize, pagenum = pagination.from_request(request)
    cycles = filters.filter(
        TestCycleList.ours(auth=request.auth).sort(
        *sort.from_request(request)).paginate(
        pagesize, pagenum), request)
    paginator = pagination.Paginator(cycles.totalResults, pagesize, pagenum)
    return TemplateResponse(
        request,
        "manage/testcycle/cycles.html",
        {"cycles": cycles, "pager": paginator}
        )



@login_redirect
def add_testcycle(request):
    form = TestCycleForm(
        request.POST or None,
        product_choices=ProductList.ours(auth=request.auth),
        team_choices=UserList.ours(auth=request.auth),
        auth=request.auth)
    if request.method == "POST":
        if form.is_valid():
            cycle = form.save()
            messages.success(
                request,
                "The test cycle '%s' has been created."  % cycle.name)
            return redirect("manage_testcycles")
    return TemplateResponse(
        request,
        "manage/testcycle/add_cycle.html",
        {"form": form}
        )



@login_redirect
def edit_testcycle(request, cycle_id):
    cycle = TestCycleList.get_by_id(cycle_id, auth=request.auth)
    form = TestCycleForm(
        request.POST or None,
        instance=cycle,
        product_choices=ProductList.ours(auth=request.auth),
        team_choices=UserList.ours(auth=request.auth),
        auth=request.auth)
    if request.method == "POST":
        actions = [(k, v) for k, v in request.POST.iteritems()
                   if k.startswith("action-")]
        if actions:
            action, run_id = actions[0]
            action = action[len("action-"):]
            if action in ["delete"]:
                run = TestRunList.get_by_id(run_id, auth=request.auth)
                try:
                    getattr(run, action)()
                except run.Conflict, e:
                    if e.response_error == "deleting.used.entity":
                        messages.error(
                            request,
                            'Cannot delete activated test run "%s."'
                            % run.name)
            return redirect(request.get_full_path())
        if form.is_valid():
            cycle = form.save()
            messages.success(
                request,
                "The test cycle '%s' has been saved."  % cycle.name)
            return redirect("manage_testcycles")

    testruns = TestRunList.ours(auth=request.auth).filter(
        testCycle=cycle.id).sort(
        *sort.from_request(request))

    return TemplateResponse(
        request,
        "manage/testcycle/edit_cycle.html",
        {
            "form": form,
            "cycle": cycle,
            "testruns": testruns,
            }
        )
