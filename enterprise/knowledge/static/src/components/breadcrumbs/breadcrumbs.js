import { Breadcrumbs } from "@web/search/breadcrumbs/breadcrumbs";

/**
 * Standard breadcrumbs without their last item: the topbar displays the
 * article hierarchy in its place.
 */
export class KnowledgeBreadcrumbs extends Breadcrumbs {
    static template = "knowledge.Breadcrumbs";
}
