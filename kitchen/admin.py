"""Django admin (/django-admin/), for troubleshooting. Day-to-day settings live on the app's own Admin page."""
from django.contrib import admin

from kitchen import models


class IngredientInline(admin.TabularInline):
    model = models.Ingredient
    extra = 0


class StepInline(admin.TabularInline):
    model = models.Step
    extra = 0


@admin.register(models.Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ['title', 'servings', 'archived', 'updated_at']
    search_fields = ['title', 'tags']
    inlines = [IngredientInline, StepInline]
    raw_id_fields = ['photo']


class MenuItemInline(admin.TabularInline):
    model = models.MenuItem
    extra = 0
    raw_id_fields = ['recipe', 'photo']


@admin.register(models.Menu)
class MenuAdmin(admin.ModelAdmin):
    list_display = ['title', 'household', 'starts_on', 'status', 'sent_at']
    list_filter = ['status']
    inlines = [MenuItemInline]


class MenuItemDishInline(admin.TabularInline):
    model = models.MenuItemDish
    extra = 0
    raw_id_fields = ['recipe']


@admin.register(models.MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'menu', 'date', 'course']
    inlines = [MenuItemDishInline]
    raw_id_fields = ['recipe', 'meal', 'photo']


class MealDishInline(admin.TabularInline):
    model = models.MealDish
    extra = 0
    raw_id_fields = ['recipe']


@admin.register(models.Meal)
class MealAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'archived', 'updated_at']
    inlines = [MealDishInline]
    raw_id_fields = ['photo']


@admin.register(models.DishPhoto)
class DishPhotoAdmin(admin.ModelAdmin):
    list_display = ['pk', 'caption', 'recipe', 'width', 'height', 'uploaded_at']
    exclude = ['image']
    raw_id_fields = ['recipe']


for model in (models.AllowedUser, models.SiteSettings, models.PreferenceCategory, models.PreferenceOption,
              models.Household, models.HouseholdPreference, models.Contact, models.Note, models.MenuFeedback,
              models.ShoppingItem, models.RecipeCategory):
    admin.site.register(model)
