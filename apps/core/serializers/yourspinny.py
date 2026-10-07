from rest_framework import serializers


class YourSpinnyRecommendationRequestSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=2000, min_length=1)


class YourSpinnyCompareRequestSerializer(serializers.Serializer):
    vehicle_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=2,
        max_length=3,
    )


class YourSpinnyQueryRequestSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=2000, min_length=1)


class YourSpinnyAskRequestSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=2000, min_length=1)
    context_filters = serializers.DictField(required=False, allow_null=True, default=dict)


class VehicleMatchReasonSerializer(serializers.Serializer):
    match_score = serializers.FloatField()
    match_reasons = serializers.ListField(child=serializers.CharField())


class VehicleRecommendationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    brand = serializers.CharField()
    model = serializers.CharField()
    variant = serializers.CharField(allow_blank=True)
    manufacturing_year = serializers.IntegerField()
    fuel_type = serializers.CharField()
    transmission = serializers.CharField()
    seating_capacity = serializers.IntegerField()
    price = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    stock_quantity = serializers.IntegerField()
    is_available = serializers.BooleanField()
    is_in_stock = serializers.BooleanField()
    dealership = serializers.IntegerField()
    dealership_name = serializers.CharField(allow_null=True)
    match_score = serializers.FloatField()
    match_reasons = serializers.ListField(child=serializers.CharField())


class YourSpinnyComparisonSerializer(serializers.Serializer):
    vehicles = VehicleRecommendationSerializer(many=True)
    analysis = serializers.CharField(allow_blank=True)
    winner = serializers.DictField(allow_null=True, required=False)


class YourSpinnyRecommendationResponseSerializer(serializers.Serializer):
    query = serializers.CharField()
    requirements = serializers.DictField(child=serializers.CharField(), required=False)
    recommendations = VehicleRecommendationSerializer(many=True)
    explanation = serializers.CharField(allow_blank=True)
    total_matches = serializers.IntegerField()


class YourSpinnyCompareResponseSerializer(serializers.Serializer):
    vehicles = VehicleRecommendationSerializer(many=True)
    comparison = serializers.CharField(allow_blank=True)


class YourSpinnyQueryResponseSerializer(serializers.Serializer):
    query = serializers.CharField()
    matches = VehicleRecommendationSerializer(many=True)
    answer = serializers.CharField(allow_blank=True)
    total_matches = serializers.IntegerField()
    intent = serializers.CharField(required=False)
    filters = serializers.DictField(child=serializers.CharField(), required=False)


class YourSpinnyAskResponseSerializer(serializers.Serializer):
    query = serializers.CharField()
    intent = serializers.CharField()
    answer = serializers.CharField(allow_blank=True)
    filters = serializers.DictField()
    results = VehicleRecommendationSerializer(many=True)
    recommendation = VehicleRecommendationSerializer(allow_null=True, required=False)
    comparison = YourSpinnyComparisonSerializer(allow_null=True, required=False)
    total_matches = serializers.IntegerField()
    no_match = serializers.BooleanField()
    closest_above = VehicleRecommendationSerializer(allow_null=True, required=False)
    processing_path = serializers.CharField(required=False)
    intent_source = serializers.CharField(required=False)
    query_type = serializers.CharField(required=False)
    context_mode = serializers.CharField(required=False)
    exclusions = serializers.DictField(required=False)
