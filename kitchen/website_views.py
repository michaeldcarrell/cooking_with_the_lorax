"""The public website (cookingwiththe.loraxglobal.com) and the workspace page that edits it."""
import logging

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from kitchen.forms import InquiryForm, ServiceForm, WebsiteTextForm
from kitchen.models import DishPhoto, Inquiry, Service, SiteSettings

logger = logging.getLogger(__name__)

PAGES = ['site_home', 'site_about', 'site_services', 'site_gallery', 'site_contact', 'site_privacy']


def _photos():
    return DishPhoto.objects.filter(on_website=True).defer('image').select_related('recipe')


def _services():
    return Service.objects.filter(active=True)


# --- public pages -------------------------------------------------------------------------------------

def home(request):
    return render(request, 'website/home.html', {'services': _services(), 'photos': _photos()[:6]})


def about(request):
    return render(request, 'website/about.html', {'photo': _photos().first()})


def services(request):
    return render(request, 'website/services.html', {'services': _services()})


def gallery(request):
    return render(request, 'website/gallery.html', {'photos': _photos()})


def contact(request):
    form = InquiryForm(request.POST or None, initial={'service': request.GET.get('service', '')})
    if request.method == 'POST' and form.is_valid():
        if form.is_spam():
            logger.info('Dropped a contact form submission that filled in the honeypot field.')
        else:
            inquiry = form.save()
            notify_inquiry(request, inquiry)
        return redirect('site_contact_thanks')
    return render(request, 'website/contact.html', {'form': form})


def contact_thanks(request):
    return render(request, 'website/thanks.html')


def privacy(request):
    return render(request, 'website/privacy.html')


def robots_txt(request):
    return HttpResponse(f'User-agent: *\nDisallow: /m/\nDisallow: /h/\n\n'
                        f'Sitemap: {settings.PUBLIC_BASE_URL}/sitemap.xml\n', content_type='text/plain')


def sitemap_xml(request):
    urls = [settings.PUBLIC_BASE_URL + reverse(name) for name in PAGES]
    return render(request, 'website/sitemap.xml', {'urls': urls}, content_type='application/xml')


def workspace_robots_txt(request):
    return HttpResponse('User-agent: *\nDisallow: /\n', content_type='text/plain')


def notify_inquiry(request, inquiry: Inquiry) -> None:
    """Email Lori about a new inquiry. A mail failure is logged; the inquiry is already saved."""
    site = SiteSettings.load()
    body = render_to_string('email/inquiry.txt', {
        'inquiry': inquiry, 'site': site, 'website_url': settings.CHEF_BASE_URL + reverse('website', urlconf='lorax.urls'),
    })
    message = EmailMessage(f'New inquiry from {" ".join(inquiry.name.split())}', body, settings.DEFAULT_FROM_EMAIL,
                           [site.contact_email or settings.MENU_REPLY_TO], reply_to=[inquiry.email])
    try:
        message.send()
    except Exception:
        logger.exception('Could not email inquiry %s', inquiry.pk)


# --- workspace: Website page --------------------------------------------------------------------------

def manage_website(request):
    site = SiteSettings.load()
    text_form = WebsiteTextForm(instance=site)
    service_form = ServiceForm(prefix='svc', initial={'order': Service.objects.count() + 1})
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'text':
            text_form = WebsiteTextForm(request.POST, instance=site)
            if text_form.is_valid():
                text_form.save()
                messages.success(request, 'Website text saved.')
                return redirect(reverse('website') + '#text')
        elif action == 'service':
            service_form = ServiceForm(request.POST, prefix='svc')
            if service_form.is_valid():
                service = service_form.save()
                messages.success(request, f'Added {service.name}.')
                return redirect(reverse('website') + '#services')
        messages.error(request, 'Please fix the errors below.')
    services = list(Service.objects.all())
    for service in services:
        service.form = ServiceForm(instance=service, prefix=f's{service.pk}')
    return render(request, 'kitchen/website.html', {
        'text_form': text_form, 'service_form': service_form,
        'services': services,
        'inquiries': Inquiry.objects.all()[:50],
        'photos': _photos(),
        'public_url': settings.PUBLIC_BASE_URL,
    })


@require_POST
def manage_service(request, pk):
    service = get_object_or_404(Service, pk=pk)
    if request.POST.get('action') == 'delete':
        service.delete()
        messages.success(request, f'Deleted {service.name}.')
    else:
        form = ServiceForm(request.POST, instance=service, prefix=f's{pk}')
        if form.is_valid():
            form.save()
            messages.success(request, f'Saved {service.name}.')
        else:
            messages.error(request, 'Name and summary are required.')
    return redirect(reverse('website') + '#services')


@require_POST
def manage_inquiry(request, pk):
    inquiry = get_object_or_404(Inquiry, pk=pk)
    if request.POST.get('action') == 'delete':
        inquiry.delete()
        messages.success(request, f'Deleted the inquiry from {inquiry.name}.')
    else:
        inquiry.handled = not inquiry.handled
        inquiry.save(update_fields=['handled'])
    return redirect(reverse('website') + '#inquiries')
