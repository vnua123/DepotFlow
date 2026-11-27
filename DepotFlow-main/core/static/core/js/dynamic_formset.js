/*
 * Dynamic formset add/remove.
 *
 * Turns a Django inline formset from "N blank rows dumped on the page
 * at once" into "one row, plus an Add button" — used on the vehicle
 * load, vehicle return, stock receipt, and sale forms.
 *
 * Expects markup like:
 *
 *   <div data-formset data-formset-prefix="form">
 *     {{ formset.management_form }}
 *     <template data-formset-empty-form>...{{ formset.empty_form }}...</template>
 *     <div data-formset-body>...one card per {{ item_form }}...</div>
 *     <button type="button" data-formset-add>Add Item</button>
 *   </div>
 *
 * Remove doesn't delete the DOM node for existing (already-saved) rows
 * — it checks that row's Django-provided DELETE checkbox and hides the
 * card, which is how Django's formset knows to delete that object on
 * save. For a row that was only just added via the Add button and
 * never saved, checking DELETE has the same safe effect: Django simply
 * skips it. Either way, TOTAL_FORMS is only ever incremented, never
 * decremented, so existing form indices never shift around.
 */
document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-formset]').forEach(function (root) {
        var prefix = root.dataset.formsetPrefix || 'form';
        var totalForms = root.querySelector('#id_' + prefix + '-TOTAL_FORMS');
        var body = root.querySelector('[data-formset-body]');
        var emptyTemplate = root.querySelector('[data-formset-empty-form]');
        var addButton = root.querySelector('[data-formset-add]');

        if (!totalForms || !body) {
            return;
        }

        function bindRemove(card) {
            var removeButton = card.querySelector('[data-formset-remove]');
            if (removeButton) {
                removeButton.addEventListener('click', function () {
                    var deleteInput = card.querySelector('input[type="checkbox"][name$="-DELETE"]');
                    if (deleteInput) {
                        deleteInput.checked = true;
                    }
                    card.classList.add('hidden');
                });
            }

            var productSelect = card.querySelector('select[name$="-product"]');
            if (productSelect && window.DepotFlow && window.DepotFlow.initProductChoice) {
                window.DepotFlow.initProductChoice(productSelect);
            }
        }

        Array.prototype.forEach.call(body.children, bindRemove);

        if (addButton && emptyTemplate) {
            addButton.addEventListener('click', function () {
                var index = parseInt(totalForms.value, 10);
                var html = emptyTemplate.innerHTML.split('__prefix__').join(index);

                var wrapper = document.createElement('div');
                wrapper.innerHTML = html.trim();
                var newCard = wrapper.firstElementChild;

                body.appendChild(newCard);
                bindRemove(newCard);
                totalForms.value = index + 1;
            });
        }
    });
});
