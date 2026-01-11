from django import forms
from .models import Empresa


class EmpresaConfigForm(forms.ModelForm):
    """Formulario para configuracoes gerais da empresa"""

    class Meta:
        model = Empresa
        fields = ['nome', 'logo', 'cor_primaria']
        widgets = {
            'nome': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nome da empresa'
            }),
            'cor_primaria': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color',
                'style': 'height: 50px; width: 100px;'
            }),
            'logo': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
        }


class WooCommerceConfigForm(forms.ModelForm):
    """Formulario para configuracoes do WooCommerce"""

    class Meta:
        model = Empresa
        fields = [
            'woo_ssh_host',
            'woo_ssh_user',
            'woo_ssh_key_path',
            'woo_db_host',
            'woo_db_port',
            'woo_db_name',
            'woo_db_user',
            'woo_db_password',
            'woo_table_prefix',
        ]
        widgets = {
            'woo_ssh_host': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: 157.245.119.130'
            }),
            'woo_ssh_user': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: root'
            }),
            'woo_ssh_key_path': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: ~/.ssh/id_ed25519'
            }),
            'woo_db_host': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: 127.0.0.1'
            }),
            'woo_db_port': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '3306'
            }),
            'woo_db_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nome do banco MySQL'
            }),
            'woo_db_user': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Usuario do banco'
            }),
            'woo_db_password': forms.PasswordInput(attrs={
                'class': 'form-control',
                'placeholder': 'Senha do banco',
                'autocomplete': 'new-password'
            }, render_value=True),
            'woo_table_prefix': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: wp_'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Mostrar valor atual da senha como asteriscos
        if self.instance and self.instance.woo_db_password:
            self.fields['woo_db_password'].widget.attrs['placeholder'] = '********'
