from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.authentication.permissions import IsAuthenticated, IsCustomer
from apps.core.exceptions import DomainError, ResourceNotFoundError
from apps.core.serializers.yourspinny import (
    YourSpinnyAskRequestSerializer,
    YourSpinnyAskResponseSerializer,
    YourSpinnyCompareRequestSerializer,
    YourSpinnyCompareResponseSerializer,
    YourSpinnyQueryRequestSerializer,
    YourSpinnyQueryResponseSerializer,
    YourSpinnyRecommendationRequestSerializer,
    YourSpinnyRecommendationResponseSerializer,
)
from apps.core.services.yourspinny_service import YourSpinnyService


class YourSpinnyAskView(APIView):
    """Unified dynamic vehicle assistant endpoint.

    Natural-language question -> Gemini structured intent -> Django validation
    -> dynamic Neon query -> verified result -> descriptive answer.
    """

    permission_classes = [IsAuthenticated, IsCustomer]

    def post(self, request):
        serializer = YourSpinnyAskRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = YourSpinnyService()
        result = service.ask(
            query=serializer.validated_data["query"],
            context_filters=serializer.validated_data.get("context_filters") or {},
        )

        return Response(
            YourSpinnyAskResponseSerializer(result).data,
            status=status.HTTP_200_OK,
        )


class YourSpinnyRecommendationView(APIView):
    permission_classes = [IsAuthenticated, IsCustomer]

    def post(self, request):
        serializer = YourSpinnyRecommendationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = YourSpinnyService()
        result = service.get_recommendations(query=serializer.validated_data["query"])

        return Response(
            YourSpinnyRecommendationResponseSerializer(result).data,
            status=status.HTTP_200_OK,
        )


class YourSpinnyCompareView(APIView):
    permission_classes = [IsAuthenticated, IsCustomer]

    def post(self, request):
        serializer = YourSpinnyCompareRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = YourSpinnyService()
        result = service.compare_vehicles(
            vehicle_ids=serializer.validated_data["vehicle_ids"],
        )

        return Response(
            YourSpinnyCompareResponseSerializer(result).data,
            status=status.HTTP_200_OK,
        )


class YourSpinnyQueryView(APIView):
    permission_classes = [IsAuthenticated, IsCustomer]

    def post(self, request):
        serializer = YourSpinnyQueryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = YourSpinnyService()
        result = service.answer_query(
            query=serializer.validated_data["query"],
        )

        return Response(
            YourSpinnyQueryResponseSerializer(result).data,
            status=status.HTTP_200_OK,
        )