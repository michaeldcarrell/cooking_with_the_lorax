from django.contrib import admin
from django.urls import include, path

from kitchen import views as v
from kitchen import website_views as w
from lorax.urls_common import common_patterns

# Lori's workspace (CHEF_BASE_URL, and any host other than the public one).

urlpatterns = [
    path('django-admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    path('welcome/', v.welcome, name='welcome'),
    path('welcome/', v.welcome, name='signin'),
    path('signout/', v.sign_out, name='signout'),
    path('robots.txt', w.workspace_robots_txt),
    path('', v.home, name='home'),

    path('clients/', v.households, name='households'),
    path('clients/<int:pk>/', v.household, name='household'),
    path('clients/<int:pk>/edit/', v.household_edit, name='household_edit'),
    path('clients/<int:pk>/delete/', v.household_delete, name='household_delete'),
    path('clients/<int:pk>/preferences/', v.household_preferences, name='household_preferences'),
    path('clients/<int:pk>/contacts/add/', v.contact_add, name='contact_add'),
    path('clients/<int:pk>/notes/add/', v.note_add, name='note_add'),
    path('clients/<int:pk>/menus/new/', v.menu_new, name='menu_new'),
    path('contacts/<int:pk>/', v.contact_edit, name='contact_edit'),
    path('notes/<int:pk>/', v.note_action, name='note_action'),

    path('menus/<int:pk>/', v.menu, name='menu'),
    path('menus/<int:pk>/delete/', v.menu_delete, name='menu_delete'),
    path('menus/<int:pk>/duplicate/', v.menu_duplicate, name='menu_duplicate'),
    path('menus/<int:pk>/items/add/', v.menu_item_add, name='menu_item_add'),
    path('menus/<int:pk>/send/', v.menu_send, name='menu_send'),
    path('menus/<int:pk>/shopping/', v.menu_shopping, name='menu_shopping'),
    path('dishes/<int:pk>/', v.menu_item_edit, name='menu_item_edit'),
    path('dishes/<int:pk>/move/<str:direction>/', v.menu_item_move, name='menu_item_move'),
    path('shopping/<int:pk>/toggle/', v.shopping_toggle, name='shopping_toggle'),
    path('shopping/<int:pk>/delete/', v.shopping_delete, name='shopping_delete'),

    path('recipes/', v.recipes, name='recipes'),
    path('recipes/new/', v.recipe_new, name='recipe_new'),
    path('recipes/<int:pk>/', v.recipe, name='recipe'),
    path('recipes/<int:pk>/edit/', v.recipe_edit, name='recipe_edit'),
    path('recipes/<int:pk>/archive/', v.recipe_archive, name='recipe_archive'),
    path('recipes/<int:pk>/photos/', v.recipe_photo_upload, name='recipe_photo_upload'),
    path('recipes/<int:pk>/photo/', v.recipe_set_photo, name='recipe_set_photo'),

    path('photos/', v.photos, name='photos'),
    path('photos/<int:pk>/', v.photo_edit, name='photo_edit'),

    path('website/', w.manage_website, name='website'),
    path('website/services/<int:pk>/', w.manage_service, name='website_service'),
    path('website/inquiries/<int:pk>/', w.manage_inquiry, name='website_inquiry'),

    path('admin/', v.manage, name='manage'),
    path('admin/options/<int:pk>/', v.manage_option, name='manage_option'),
    path('admin/categories/<int:pk>/', v.manage_category, name='manage_category'),
    path('admin/access/<int:pk>/', v.manage_user, name='manage_user'),
] + common_patterns
