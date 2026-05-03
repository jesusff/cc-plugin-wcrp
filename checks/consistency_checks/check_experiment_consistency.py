#!/usr/bin/env python

from compliance_checker.base import TestCtx

try:
    import esgvoc.api as voc
    ESG_VOCAB_AVAILABLE = True
except ImportError:
    ESG_VOCAB_AVAILABLE = False


# ============================================================================
# Mapping visible: attribute name stays the same in the NetCDF file,
# only the ESGVOC collection name changes between CMIP6 and CMIP7.
# ============================================================================
CV_COLLECTION_MAP = {
    "cmip6": {
        "experiment_id": "experiment_id",
    },
    "cmip7": {
        "experiment_id": "experiment",
    },
    "cmip6plus": {
        "experiment_id": "experiment_id",
    },
}


def _get_cv_collection(project_id, attribute_name):
    project_key = str(project_id).strip().lower()
    return CV_COLLECTION_MAP.get(project_key, {}).get(attribute_name, attribute_name)


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _lower_str_list(values):
    return [str(v).strip().lower() for v in _as_list(values) if v is not None]


def _get_global_attr(ds, attr_name, missing_attrs):
    """
    Return the stripped global attribute value if present, else None.
    Track missing attributes in missing_attrs without raising.
    """
    if attr_name not in ds.ncattrs():
        missing_attrs.append(attr_name)
        return None
    return str(ds.getncattr(attr_name)).strip()


def check_experiment_consistency(ds, severity, project_id="cmip6"):
    """
    [ATTR007] Checks if attributes are consistent with the 'experiment_id'
    from Esgvoc
    """
    fixed_check_id = "ATTR007"
    description = f"[{fixed_check_id}] Consistency: experiment_id vs other global attributes"
    ctx = TestCtx(severity, description)

    if not ESG_VOCAB_AVAILABLE:
        ctx.add_failure("The 'esgvoc' library is not installed.")
        return [ctx.to_result()]

    try:
        failures = []
        missing_attrs = []

        # Read all file attributes independently so one missing attribute does
        # not prevent the other comparisons from running.
        actual_experiment_id = _get_global_attr(ds, "experiment_id", missing_attrs)
        actual_activity_id = _get_global_attr(ds, "activity_id", missing_attrs)
        actual_experiment = _get_global_attr(ds, "experiment", missing_attrs)
        actual_parent_id = _get_global_attr(ds, "parent_experiment_id", missing_attrs)
        actual_sub_experiment_id = _get_global_attr(ds, "sub_experiment_id", missing_attrs)

        reference_term = None

        # We can only query the CV if experiment_id exists in the file.
        if actual_experiment_id is not None:
            collection_id = _get_cv_collection(project_id, "experiment_id")

            reference_term = voc.get_term_in_collection(
                project_id=project_id,
                collection_id=collection_id,
                term_id=actual_experiment_id,
            )

            # Fallback: if the term is not found by term_id, try to resolve the
            # underlying ESGVOC id from an exact drs_name match.
            if not reference_term:
                candidates = voc.find_terms_in_collection(
                    project_id=project_id,
                    collection_id=collection_id,
                    expression=actual_experiment_id,
                    selected_term_fields=["id", "drs_name"],
                )

                resolved_term_id = None

                for item in candidates:
                    candidate_drs_name = str(getattr(item, "drs_name", "")).strip()
                    candidate_id = str(getattr(item, "id", "")).strip()

                    if candidate_drs_name == actual_experiment_id:
                        resolved_term_id = candidate_id
                        break

                if resolved_term_id:
                    reference_term = voc.get_term_in_collection(
                        project_id=project_id,
                        collection_id=collection_id,
                        term_id=resolved_term_id,
                    )

            if not reference_term:
                failures.append(
                    f"The experiment_id '{actual_experiment_id}' was not found in the ESGF vocabulary."
                )

        # Compare against the CV only when both the CV term and the file
        # attribute needed for that comparison are available.
        if reference_term:
            expected_activity_ids = getattr(reference_term, "activity_id", None)
            if expected_activity_ids and actual_activity_id is not None:
                expected_activity_ids_norm = _lower_str_list(expected_activity_ids)
                if actual_activity_id.lower() not in expected_activity_ids_norm:
                    failures.append(
                        f"Inconsistency for 'activity_id': CV expects one of {list(_as_list(expected_activity_ids))}, "
                        f"file has '{actual_activity_id}'."
                    )

            expected_experiment = getattr(reference_term, "experiment", None)
            if expected_experiment and actual_experiment is not None:
                if actual_experiment != str(expected_experiment).strip():
                    failures.append(
                        f"Inconsistency for 'experiment': CV expects '{expected_experiment}', "
                        f"file has '{actual_experiment}'."
                    )

            expected_parent_ids = getattr(reference_term, "parent_experiment_id", None)
            if expected_parent_ids and actual_parent_id is not None:
                expected_parent_ids_norm = _lower_str_list(expected_parent_ids)
                if actual_parent_id.lower() not in expected_parent_ids_norm:
                    failures.append(
                        f"Inconsistency for 'parent_experiment_id': CV expects one of {list(_as_list(expected_parent_ids))}, "
                        f"file has '{actual_parent_id}'."
                    )

            expected_sub_experiment_ids = getattr(reference_term, "sub_experiment_id", None)
            if expected_sub_experiment_ids and actual_sub_experiment_id is not None:
                expected_sub_ids_norm = _lower_str_list(expected_sub_experiment_ids)
                if actual_sub_experiment_id.lower() not in expected_sub_ids_norm:
                    failures.append(
                        f"Inconsistency for 'sub_experiment_id': CV expects one of {list(_as_list(expected_sub_experiment_ids))}, "
                        f"file has '{actual_sub_experiment_id}'."
                    )

        # Report each missing attribute separately with its exact name.
        for attr_name in missing_attrs:
            failures.append(f"Missing required global attribute: '{attr_name}'.")

        if not failures:
            ctx.add_pass()
        else:
            for failure in failures:
                ctx.add_failure(failure)

    except Exception as e:
        ctx.add_failure(f"An unexpected error occurred: {e}")

    return [ctx.to_result()]