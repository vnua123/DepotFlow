/*
 * Searchable product dropdowns.
 *
 * Targets:
 *   - select[name$="-product"]  -> the "product" field on any
 *     formset row (vehicle load items, return items, stock receipt
 *     items, sale items) — Django's default formset prefix is
 *     "form", so these render as name="form-0-product", etc.
 *   - select[name="product"]    -> a plain (non-formset) product field,
 *     if one is ever added outside a formset.
 *   - select[name="products"]   -> Promotion's multi-select product
 *     picker.
 *
 * Exposes window.DepotFlow.initProductChoice(selectEl) so
 * dynamic_formset.js can enhance a product <select> the moment a new
 * formset row is cloned in — Choices.js only enhances the elements
 * you hand it, it doesn't watch the DOM for new ones on its own.
 */
window.DepotFlow = window.DepotFlow || {};

window.DepotFlow.initProductChoice = function (selectEl) {
    if (!selectEl || selectEl.dataset.choicesInitialized) {
        return;
    }
    selectEl.dataset.choicesInitialized = "true";

    new Choices(selectEl, {
        searchEnabled: true,
        searchResultLimit: -1,
        searchPlaceholderValue: "Search products…",
        itemSelectText: "",
        shouldSort: false,
        placeholder: true,
        placeholderValue: "Select a product",
        fuseOptions: { threshold: 0.3 },
    });
};

document.addEventListener('DOMContentLoaded', function () {
    document
        .querySelectorAll('select[name$="-product"], select[name="product"], select[name="products"]')
        .forEach(window.DepotFlow.initProductChoice);
});

