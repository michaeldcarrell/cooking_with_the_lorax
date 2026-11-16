from django import forms

from kitchen.models import (
    AllowedUser, Contact, DishPhoto, Household, Menu, MenuItem, PreferenceCategory, PreferenceOption, Recipe,
    SiteSettings,
)

DATE = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


class HouseholdForm(forms.ModelForm):
    class Meta:
        model = Household
        fields = ['name', 'address', 'default_servings', 'preference_notes', 'archived']
        widgets = {'address': forms.Textarea(attrs={'rows': 2}), 'preference_notes': forms.Textarea(attrs={'rows': 3})}
        labels = {'archived': 'Archived (no longer a client)'}


class NewHouseholdForm(forms.ModelForm):
    class Meta:
        model = Household
        fields = ['name', 'default_servings']
        labels = {'name': 'Household name'}


class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = ['name', 'email', 'phone', 'role', 'receives_menus']
        labels = {'receives_menus': 'Send menus to this person'}


class NoteForm(forms.Form):
    body = forms.CharField(widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Add a note…'}), label='')
    pinned = forms.BooleanField(required=False, label='Pin to top')


class RecipeForm(forms.ModelForm):
    class Meta:
        model = Recipe
        fields = ['title', 'description', 'servings', 'prep_minutes', 'cook_minutes', 'tags', 'chef_notes',
                  'source_url', 'photo']
        widgets = {'description': forms.Textarea(attrs={'rows': 2}), 'chef_notes': forms.Textarea(attrs={'rows': 3}),
                   # Shown as removable badges by static/js/app.js; still saved as comma-separated text.
                   'tags': forms.TextInput(attrs={'data-tag-input': 'tag-options'})}
        labels = {'prep_minutes': 'Prep (min)', 'cook_minutes': 'Cook (min)', 'source_url': 'Source link'}
        help_texts = {'tags': 'Press Enter or comma after each tag, e.g. gluten-free, dinner, freezer-friendly'}

    def clean_tags(self):
        tags = [t.strip().lower() for t in self.cleaned_data['tags'].split(',') if t.strip()]
        return ', '.join(dict.fromkeys(tags))[:300]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['photo'].queryset = DishPhoto.objects.defer('image')
        self.fields['photo'].required = False


class MenuForm(forms.ModelForm):
    class Meta:
        model = Menu
        fields = ['title', 'starts_on', 'ends_on', 'intro', 'status']
        widgets = {'starts_on': DATE, 'ends_on': DATE, 'intro': forms.Textarea(attrs={'rows': 3})}
        labels = {'starts_on': 'From', 'ends_on': 'To', 'intro': 'Note to the client'}

    def clean(self):
        data = super().clean()
        if data.get('starts_on') and data.get('ends_on') and data['ends_on'] < data['starts_on']:
            self.add_error('ends_on', 'Ends before it starts.')
        return data


class NewMenuForm(forms.ModelForm):
    class Meta:
        model = Menu
        fields = ['title', 'starts_on', 'ends_on']
        widgets = {'starts_on': DATE, 'ends_on': DATE}
        labels = {'starts_on': 'From', 'ends_on': 'To'}


class MenuItemForm(forms.ModelForm):
    class Meta:
        model = MenuItem
        fields = ['date', 'course', 'recipe', 'servings', 'title', 'description', 'photo']
        widgets = {'date': DATE, 'description': forms.Textarea(attrs={'rows': 2}),
                   'course': forms.TextInput(attrs={'list': 'course-options'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['recipe'].queryset = Recipe.objects.filter(archived=False)
        self.fields['photo'].queryset = DishPhoto.objects.defer('image')

    def clean(self):
        data = super().clean()
        if not data.get('recipe') and not data.get('title'):
            raise forms.ValidationError('Pick a recipe or give the dish a title.')
        return data


class SendMenuForm(forms.Form):
    recipients = forms.MultipleChoiceField(widget=forms.CheckboxSelectMultiple, label='Send to')
    extra = forms.EmailField(required=False, label='Also send to (optional)')

    def __init__(self, *args, contacts=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['recipients'].choices = [(c.email, f'{c.name} <{c.email}>') for c in contacts if c.email]
        self.fields['recipients'].required = False
        self.fields['recipients'].initial = [c.email for c in contacts if c.email and c.receives_menus]

    def clean(self):
        data = super().clean()
        addresses = list(data.get('recipients') or [])
        if data.get('extra'):
            addresses.append(data['extra'])
        if not addresses:
            raise forms.ValidationError('Choose at least one person to send it to.')
        data['addresses'] = list(dict.fromkeys(addresses))
        return data


class PhotoUploadForm(forms.Form):
    caption = forms.CharField(required=False, max_length=200, help_text='Optional. Used for all photos in this upload.')
    recipe = forms.ModelChoiceField(queryset=Recipe.objects.filter(archived=False), required=False,
                                    help_text='Optional. The first photo becomes the recipe\'s photo if it has none.')


class PhotoEditForm(forms.ModelForm):
    class Meta:
        model = DishPhoto
        fields = ['caption', 'recipe']


class SiteSettingsForm(forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = ['business_name', 'chef_name', 'contact_email', 'menu_footer']
        widgets = {'menu_footer': forms.Textarea(attrs={'rows': 2})}
        labels = {'contact_email': 'Client replies go to'}


class CategoryForm(forms.ModelForm):
    class Meta:
        model = PreferenceCategory
        fields = ['name', 'help_text', 'order']


class OptionForm(forms.ModelForm):
    class Meta:
        model = PreferenceOption
        fields = ['category', 'name']


class AllowedUserForm(forms.ModelForm):
    class Meta:
        model = AllowedUser
        fields = ['email', 'is_admin']
        labels = {'email': 'Google account email', 'is_admin': 'Admin'}

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()
