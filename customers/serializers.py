from rest_framework import serializers
from .models import Customer, Cart, Order, CustomerAnalysis

class CartSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cart
        fields = [
            'id', 'checkout_id', 'cart_total', 'status', 
            'items_count', 'created_at', 'abandoned_at'
        ]

class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'total', 'status', 
            'created_at', 'items_count'
        ]

class CustomerSerializer(serializers.ModelSerializer):
    whatsapp_number = serializers.ReadOnlyField()
    full_name = serializers.ReadOnlyField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    recent_carts = CartSerializer(source='carts', many=True, read_only=True)
    recent_orders = OrderSerializer(source='orders', many=True, read_only=True)
    
    class Meta:
        model = Customer
        fields = [
            'id', 'email', 'phone', 'whatsapp_number',
            'first_name', 'last_name', 'full_name',
            'status', 'status_display', 'score',
            'total_orders', 'completed_orders', 'total_spent',
            'abandoned_carts', 'total_abandoned_value',
            'days_since_last_purchase', 'last_activity',
            'recent_carts', 'recent_orders',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'score', 'status', 'total_orders', 'completed_orders',
            'total_spent', 'abandoned_carts', 'total_abandoned_value'
        ]

class CustomerListSerializer(serializers.ModelSerializer):
    """Versão simplificada para listagens"""
    whatsapp_number = serializers.ReadOnlyField()
    full_name = serializers.ReadOnlyField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = Customer
        fields = [
            'id', 'email', 'phone', 'whatsapp_number',
            'full_name', 'status', 'status_display', 
            'score', 'total_spent', 'last_activity'
        ]

class CustomerWhatsAppExportSerializer(serializers.ModelSerializer):
    """Serializer para exportação WhatsApp"""
    nome = serializers.CharField(source='full_name')
    whatsapp = serializers.CharField(source='whatsapp_number')
    
    class Meta:
        model = Customer
        fields = ['nome', 'whatsapp', 'email', 'status', 'score']