/*
 * "Available stock at this depot" hint.
 *
 * Opt-in per page via a wrapper element, using EITHER a depot field
 * OR a salesman field as the reference for which depot's stock to
 * check (the load form has no depot field of its own anymore — it's
 * derived from the picked salesman — so this supports both):
 *
 *   <div data-stock-hint data-depot-field="id_depot">
 *   <div data-stock-hint data-salesman-field="id_salesman">
 *     ... formset with product selects, each row also containing a
 *     <p data-stock-hint-text></p> placeholder (see
 *     partials/dynamic_formset.html's show_stock_hint option) ...
 *   </div>
 *
 * Refetches when: a product field changes, or the reference field
 * changes (which refreshes every visible row, since they're all now
 * asking about a different depot). Uses event delegation on the
 * wrapper so newly added formset rows (via the Add Item button) are
 * covered automatically, with no extra wiring needed here.
 */
document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-stock-hint]').forEach(function (root) {
        var depotField = root.dataset.depotField ? document.getElementById(root.dataset.depotField) : null;
        var salesmanField = root.dataset.salesmanField ? document.getElementById(root.dataset.salesmanField) : null;
        var referenceField = depotField || salesmanField;
        var paramName = depotField ? 'depot' : 'salesman';

        if (!referenceField) {
            return;
        }

        function hintFor(productSelect) {
            var card = productSelect.closest('.formset-card');
            return card ? card.querySelector('[data-stock-hint-text]') : null;
        }

        function refresh(productSelect) {
            var hint = hintFor(productSelect);
            if (!hint) {
                return;
            }

            var referenceId = referenceField.value;
            var productId = productSelect.value;

            if (!referenceId || !productId) {
                hint.textContent = '';
                return;
            }

            hint.textContent = 'Checking stock…';
            hint.classList.remove('text-depot-brick');
            hint.classList.add('text-stone-500');

            var url = '/inventory/stock-balance/?product=' + encodeURIComponent(productId) +
                '&' + paramName + '=' + encodeURIComponent(referenceId);

            fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                .then(function (response) {
                    return response.ok ? response.json() : Promise.reject();
                })
                .then(function (data) {
                    hint.textContent = 'Available at this depot: ' + data.stock_balance;
                    if (data.stock_balance <= 0) {
                        hint.classList.remove('text-stone-500');
                        hint.classList.add('text-depot-brick');
                    }
                })
                .catch(function () {
                    hint.textContent = '';
                });
        }

        root.addEventListener('change', function (event) {
            if (event.target.matches('select[name$="-product"]')) {
                refresh(event.target);
            }
        });

        referenceField.addEventListener('change', function () {
            root.querySelectorAll('select[name$="-product"]').forEach(refresh);
        });

        // Cover rows already selected on initial page load (e.g. editing).
        root.querySelectorAll('select[name$="-product"]').forEach(function (select) {
            if (select.value) {
                refresh(select);
            }
        });
    });
});
