from rest_framework import permissions

from apps.core.authentication.supabase import SupabaseUser


class IsAuthenticated(permissions.BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.user, SupabaseUser)


class IsCustomer(permissions.BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.user, SupabaseUser) and request.user.is_customer


class IsEmployee(permissions.BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.user, SupabaseUser) and request.user.is_employee


class IsTechnician(permissions.BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.user, SupabaseUser) and request.user.is_technician


class IsAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.user, SupabaseUser) and request.user.is_admin


class IsOwnerOrAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.user, SupabaseUser) and request.user.is_owner_or_admin


class IsEmployeeOrAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.user, SupabaseUser) and request.user.is_employee_or_admin


class IsTechnicianOrAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.user, SupabaseUser) and request.user.is_technician_or_admin


class IsStaff(permissions.BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.user, SupabaseUser) and request.user.is_staff


class IsCustomerOrEmployeeOrAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return isinstance(user, SupabaseUser) and (user.is_customer or user.is_employee_or_admin)


class IsOwner(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        user = request.user
        if not isinstance(user, SupabaseUser):
            return False

        if user.is_customer and user.customer_profile:
            if hasattr(obj, "customer"):
                return obj.customer_id == user.customer_profile.pk
            if hasattr(obj, "customer_vehicle"):
                return obj.customer_vehicle.customer_id == user.customer_profile.pk
            if isinstance(obj, user.customer_profile.__class__):
                return obj.pk == user.customer_profile.pk

        if user.is_employee and user.employee_profile:
            if hasattr(obj, "dealership"):
                return obj.dealership_id == user.employee_profile.dealership_id
            if hasattr(obj, "employee"):
                return obj.employee_id == user.employee_profile.pk

        return False


class IsDealershipMember(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not isinstance(user, SupabaseUser) or not user.is_employee:
            return False

        dealership_id = view.kwargs.get("dealership_id") or request.query_params.get("dealership")
        if dealership_id:
            try:
                return int(dealership_id) == user.dealership_id
            except (ValueError, TypeError):
                return False

        return True

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not isinstance(user, SupabaseUser) or not user.is_employee:
            return False

        if hasattr(obj, "dealership"):
            return obj.dealership_id == user.dealership_id

        return False


class IsTechnicianAssigned(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        user = request.user
        if not isinstance(user, SupabaseUser) or not user.is_technician:
            return False

        if not user.employee_profile:
            return False

        if hasattr(obj, "technician"):
            return obj.technician.employee_id == user.employee_profile.pk
        if hasattr(obj, "assignments"):
            return obj.assignments.filter(technician__employee_id=user.employee_profile.pk).exists()

        return False


class CanAccessCustomerResource(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        user = request.user
        if not isinstance(user, SupabaseUser):
            return False

        if user.is_admin:
            return True

        if user.is_customer and user.customer_profile:
            customer_id = getattr(obj, "customer_id", None)
            if customer_id is None and hasattr(obj, "customer_vehicle"):
                customer_id = obj.customer_vehicle.customer_id
            return customer_id == user.customer_profile.pk

        if user.is_employee and user.employee_profile:
            if hasattr(obj, "dealership"):
                return obj.dealership_id == user.employee_profile.dealership_id
            if hasattr(obj, "customer_vehicle") and hasattr(obj.customer_vehicle, "customer"):
                appointment = getattr(obj, "appointment", None)
                if appointment:
                    return appointment.dealership_id == user.employee_profile.dealership_id

        return False