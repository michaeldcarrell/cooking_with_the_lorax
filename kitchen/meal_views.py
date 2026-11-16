"""Meals: saved combinations of recipes (a main with sides, say), and meals on menus."""
from django.contrib import messages
from django.db import transaction
from django.db.models import Max, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from kitchen.forms import MealForm, MenuMealForm
from kitchen.models import Meal, MealDish, Menu, MenuItem, MenuItemDish, Recipe, RecipeCategory


def recipe_groups() -> list[tuple[str, list[Recipe]]]:
    """Active recipes grouped by category, for mix-and-match pickers. A recipe in two categories appears in
    both groups; recipes with no category come last under "Other"."""
    recipes = list(Recipe.objects.filter(archived=False).prefetch_related('categories').only('id', 'title'))
    groups = []
    for category in RecipeCategory.objects.all():
        members = [r for r in recipes if any(c.pk == category.pk for c in r.categories.all())]
        if members:
            groups.append((category.name, members))
    other = [r for r in recipes if not r.categories.all()]
    if other:
        groups.append(('Other' if groups else 'Recipes', other))
    return groups


def _recipe_from_post(request) -> Recipe | None:
    try:
        return Recipe.objects.filter(pk=int(request.POST.get('recipe', '')), archived=False).first()
    except ValueError:
        return None


def _move(siblings: list, obj, direction: str) -> None:
    """Swap `obj` with its neighbour in `siblings` (ordered), renumbering so orders are distinct."""
    index = siblings.index(obj)
    other = index - 1 if direction == 'up' else index + 1
    if 0 <= other < len(siblings):
        siblings[index], siblings[other] = siblings[other], siblings[index]
    for order, sibling in enumerate(siblings):
        if sibling.order != order:
            sibling.order = order
            sibling.save(update_fields=['order'])


def meal_prefetch():
    return Prefetch('dishes', queryset=MealDish.objects.select_related('recipe__photo')
                    .defer('recipe__photo__image').prefetch_related('recipe__categories'))


# --- saved meals --------------------------------------------------------------------------------------

def meals(request):
    query = request.GET.get('q', '').strip()
    category = request.GET.get('category', '')
    show_archived = request.GET.get('archived') == '1'
    qs = Meal.objects.filter(archived=show_archived).select_related('photo').defer('photo__image') \
        .prefetch_related(meal_prefetch())
    if query:
        qs = qs.filter(Q(name__icontains=query) | Q(description__icontains=query) |
                       Q(dishes__recipe__title__icontains=query)).distinct()
    if category.isdigit():
        qs = qs.filter(dishes__recipe__categories=category).distinct()
    return render(request, 'kitchen/meals.html', {
        'meals': qs, 'query': query, 'show_archived': show_archived, 'category': category,
        'categories': RecipeCategory.objects.all(),
    })


@require_POST
def meal_new(request):
    meal = Meal.objects.create()
    recipe = _recipe_from_post(request)
    if recipe:
        MealDish.objects.create(meal=meal, recipe=recipe, order=0)
    return redirect(meal)


def meal(request, pk):
    meal = get_object_or_404(Meal.objects.prefetch_related(meal_prefetch()), pk=pk)
    form = MealForm(request.POST or None, instance=meal)
    if request.method == 'POST':
        if request.POST.get('delete'):
            name = meal.display_name()
            meal.delete()
            messages.success(request, f'Deleted {name}. Menus that use it keep their dishes.')
            return redirect('meals')
        if form.is_valid():
            form.save()
            messages.success(request, 'Meal saved.')
            return redirect(meal)
    used_on = (MenuItem.objects.filter(meal=meal).select_related('menu__household')
               .order_by('-menu__starts_on')[:10])
    return render(request, 'kitchen/meal.html', {
        'meal': meal, 'form': form, 'dishes': meal.dishes.all(), 'groups': recipe_groups(), 'used_on': used_on,
    })


@require_POST
def meal_dish(request, pk):
    """Add, swap, remove or move one of a saved meal's dishes."""
    meal = get_object_or_404(Meal, pk=pk)
    action = request.POST.get('action')
    dishes = list(meal.dishes.all())
    dish = next((d for d in dishes if str(d.pk) == request.POST.get('dish')), None)
    if action == 'add':
        recipe = _recipe_from_post(request)
        if recipe:
            MealDish.objects.create(meal=meal, recipe=recipe, order=(dishes[-1].order + 1) if dishes else 0)
    elif dish and action == 'swap':
        recipe = _recipe_from_post(request)
        if recipe:
            dish.recipe = recipe
            dish.save(update_fields=['recipe'])
    elif dish and action == 'remove':
        dish.delete()
    elif dish and action in ('up', 'down'):
        _move(dishes, dish, action)
    meal.save(update_fields=['updated_at'])
    return redirect(reverse('meal', args=[pk]) + '#dishes')


# --- meals on menus -----------------------------------------------------------------------------------

@require_POST
@transaction.atomic
def menu_meal_add(request, pk):
    menu = get_object_or_404(Menu, pk=pk)
    form = MenuMealForm(request.POST, prefix='meal')
    if not form.is_valid():
        messages.error(request, 'Pick a meal and the number of servings.')
        return redirect(reverse('menu', args=[pk]) + '#dishes')
    meal = form.cleaned_data['meal']
    recipes = meal.recipes()
    if not recipes:
        messages.error(request, f'{meal.display_name()} has no dishes yet.')
        return redirect(reverse('menu', args=[pk]) + '#dishes')
    # Copy the meal so later swaps on this menu don't change the saved meal (and vice versa).
    item = MenuItem.objects.create(
        menu=menu, meal=meal, title=meal.name, description=meal.description, photo=meal.photo,
        date=form.cleaned_data['date'], course=form.cleaned_data['course'], servings=form.cleaned_data['servings'],
        order=(menu.items.aggregate(m=Max('order'))['m'] or 0) + 1)
    MenuItemDish.objects.bulk_create([MenuItemDish(item=item, recipe=r, order=i) for i, r in enumerate(recipes)])
    messages.success(request, f'Added {meal.display_name()}.')
    return redirect(reverse('menu', args=[pk]) + '#dishes')


@require_POST
@transaction.atomic
def menu_item_dish(request, pk):
    """Add, swap, remove or move a dish of one menu entry. Changes this menu only."""
    item = get_object_or_404(MenuItem, pk=pk)
    action = request.POST.get('action')
    if action == 'add' and item.recipe_id:
        # A single dish becomes a meal: its recipe turns into the first dish.
        MenuItemDish.objects.create(item=item, recipe_id=item.recipe_id, order=0)
        item.recipe = None
        item.save(update_fields=['recipe'])
    dishes = list(item.dishes.all())
    dish = next((d for d in dishes if str(d.pk) == request.POST.get('dish')), None)
    if action == 'add':
        recipe = _recipe_from_post(request)
        if recipe:
            MenuItemDish.objects.create(item=item, recipe=recipe, order=(dishes[-1].order + 1) if dishes else 0)
    elif dish and action == 'swap':
        recipe = _recipe_from_post(request)
        if recipe:
            dish.recipe = recipe
            dish.save(update_fields=['recipe'])
    elif dish and action == 'remove':
        if len(dishes) > 1:
            dish.delete()
        else:
            messages.error(request, 'A meal needs at least one dish. Remove the whole entry instead.')
    elif dish and action in ('up', 'down'):
        _move(dishes, dish, action)
    return redirect(reverse('menu_item_edit', args=[pk]) + '#dishes')


@require_POST
@transaction.atomic
def menu_item_save_meal(request, pk):
    """Save a menu entry's dishes as a new meal in the library."""
    item = get_object_or_404(MenuItem, pk=pk)
    recipes = item.recipes()
    if not recipes:
        messages.error(request, 'This entry has no recipes to save.')
        return redirect('menu_item_edit', pk)
    meal = Meal.objects.create(name=item.title, description=item.description, photo=item.photo)
    MealDish.objects.bulk_create([MealDish(meal=meal, recipe=r, order=i) for i, r in enumerate(recipes)])
    messages.success(request, f'Saved {meal.display_name()} to Meals.')
    return redirect(meal)
