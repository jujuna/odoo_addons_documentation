from collections import defaultdict

from odoo import models


class MarketingActivity(models.Model):
    _inherit = 'marketing.activity'

    def action_delete_step(self, step_type, cascade_delete=False):
        if cascade_delete and self.child_ids:
            self.child_ids.action_delete_step(step_type, cascade_delete)
            return self._unlink_activity()
        elif cascade_delete:
            return self._unlink_activity()
        if step_type == 'delay':
            self._delete_delay()
        elif step_type == 'trigger':
            self._delete_interaction()
        else:
            self._delete_marketing_activity()

    def _delete_delay(self):
        """
            Used to remove the delay node off the tree in the campaign flow view.
            To do that we set its interval_number to 0.
            If the impacted node will become empty, we remove it.
        """
        activities_to_keep = self.filtered(
            lambda activity: activity._has_activity_node() or activity._has_trigger_node())
        for activity in activities_to_keep:
            coordinates = dict(activity.view_coordinates or {})
            coordinates.pop('delay', None)
            activity.write({
                'interval_number': 0,
                'view_coordinates': coordinates,
            })
        (self - activities_to_keep)._unlink_activity()

    def _delete_interaction(self):
        """
            Used to remove the trigger node off the tree in the campaign flow view.
            To do that we set its trigger_type back to activity or begin, depending if the activity has a parent or not.
            If the impacted node will become empty, we remove it.
        """
        activities_to_keep = self.filtered(
            lambda activity: activity._has_delay_node() or activity._has_activity_node())
        for activity in activities_to_keep:
            coordinates = dict(activity.view_coordinates or {})
            coordinates.pop('trigger', None)
            activity.write({
                'trigger_type': 'activity' if activity.parent_id else 'begin',
                'triggering_activity_id': False,
                'wait_value_domain': False,
                'view_coordinates': coordinates,
            })
        (self - activities_to_keep)._unlink_activity()

    def _delete_marketing_activity(self):
        """
            Used to remove an activity off the tree in the campaign flow view.
            To do that, we set the activity_type to `structure` so that the activity disappears from the tree.
            But we still keep the information linked to their options, interval_number/interval_type, trigger_type, etc.
            If the impacted node will become empty, we remove it.
        """
        activities_to_keep = self.filtered(
            lambda activity: activity._has_delay_node() or activity._has_trigger_node())
        for activity in activities_to_keep:
            coordinates = dict(activity.view_coordinates or {})
            coordinates.pop('activity', None)
            activity_values = {'activity_type': 'structure'}
            if activity.activity_type == 'split':
                activity_values.update({
                    'trigger_type': 'activity' if activity.parent_id else 'begin',
                    'triggering_activity_id': False,
                    'split_domain': False,
                })
                if not activity.child_ids:
                    if activity._has_delay_node() and 'delay' in coordinates:
                        last_node_coordinates = coordinates['delay']
                    elif activity._has_trigger_node() and 'trigger' in coordinates:
                        last_node_coordinates = coordinates['trigger']
                    else:
                        last_node_coordinates = self.env['marketing.campaign']._get_last_visible_node_coordinates(activity.parent_id)
                    coordinates.pop('no_branch_flag', None)
                    coordinates.pop('yes_branch_flag', None)
                    coordinates.update({
                        'flag': {
                            'x': last_node_coordinates['x'] + 350,
                            'y': last_node_coordinates['y'],
                        },
                    })
            activity_values.update({
                'view_coordinates': coordinates,
            })
            activity.write(activity_values)
        (self - activities_to_keep)._unlink_activity()

    def _unlink_activity(self):
        """
            Used to delete an activity and all its fake nodes.
            The method updates the flag position of the new leaf nodes and
            reconnects the nodes so that the children of the node being deleted
            are connected to the parent of that node.
        """
        for activity_to_unlink in self:
            campaign = activity_to_unlink.campaign_id
            # Step 1: Update the flags

            if activity_to_unlink.parent_id:
                # Update the flag position of the yes/no branches:
                if activity_to_unlink.parent_id.activity_type == 'split' and not activity_to_unlink.child_ids:
                    split_node = activity_to_unlink.parent_id
                    remaining_children = split_node.child_ids.filtered(
                        lambda activity: activity not in self and activity.is_split_no == activity_to_unlink.is_split_no)
                    if not remaining_children:
                        if activity_to_unlink._has_trigger_node() and 'trigger' in activity_to_unlink.view_coordinates:
                            first_node_coordinates = activity_to_unlink.view_coordinates['trigger']
                        elif activity_to_unlink._has_delay_node() and 'delay' in activity_to_unlink.view_coordinates:
                            first_node_coordinates = activity_to_unlink.view_coordinates['delay']
                        elif activity_to_unlink._has_activity_node() and 'activity' in activity_to_unlink.view_coordinates:
                            first_node_coordinates = activity_to_unlink.view_coordinates['activity']
                        else:
                            first_node_coordinates = activity_to_unlink.view_coordinates.get('flag', {'x': 0, 'y': 0})
                        split_node_coordinates = dict(split_node.view_coordinates or {})
                        split_node_coordinates.update({
                            'no_branch_flag' if activity_to_unlink.is_split_no else 'yes_branch_flag': {
                                'x': first_node_coordinates['x'],
                                'y': first_node_coordinates['y'],
                            },
                        })
                        split_node.write({
                            'view_coordinates': split_node_coordinates,
                        })
                # Update the flag position of the parent node:
                elif not activity_to_unlink.child_ids:
                    parent_node = activity_to_unlink.parent_id
                    remaining_cousin_nodes = parent_node.child_ids - self
                    if not remaining_cousin_nodes:
                        # When the parent marketing activity will become a leaf:
                        last_visible_node_coordinates = campaign._get_last_visible_node_coordinates(parent_node)
                        parent_node_coordinates = dict(parent_node.view_coordinates or {})
                        parent_node_coordinates.update({
                            'flag': {
                                'x': last_visible_node_coordinates['x'] + 350,
                                'y': last_visible_node_coordinates['y'],
                            },
                        })
                        parent_node.write({
                            'view_coordinates': parent_node_coordinates,
                        })
            elif not activity_to_unlink.child_ids:
                campaign_coordinates = dict(campaign.view_coordinates) if campaign.view_coordinates else defaultdict(lambda: {'x': 0, 'y': 0})
                if activity_to_unlink.trigger_type == 'collect_reply':
                    # Update the flag position of the reply trigger:
                    remaining_root_nodes_triggered_by_reply_trigger = campaign.marketing_activity_ids.filtered(lambda activity:
                        activity not in self
                        and not activity.parent_id
                        and activity.trigger_type == 'collect_reply')
                    if not remaining_root_nodes_triggered_by_reply_trigger:
                        campaign_coordinates.update({
                            'reply_trigger_flag': {
                                'x': campaign_coordinates.get('reply_trigger', {'x': 0})['x'] + 350,
                                'y': campaign_coordinates.get('reply_trigger', {'y': 0})['y']
                            },
                        })
                        campaign.write({
                            'view_coordinates': campaign_coordinates
                        })
                else:
                    # Update the flag position of the main trigger:
                    remaining_root_nodes_triggered_by_main_trigger = campaign.marketing_activity_ids.filtered(lambda activity:
                        activity not in self
                        and not activity.parent_id
                        and activity.trigger_type != 'collect_reply')
                    if not remaining_root_nodes_triggered_by_main_trigger:
                        campaign_coordinates.update({
                            'trigger_flag': {
                                'x': campaign_coordinates['trigger']['x'] + 350,
                                'y': campaign_coordinates['trigger']['y']
                            },
                        })
                        campaign.write({
                            'view_coordinates': campaign_coordinates
                        })

            # Step 2: Connect the children of the node to be deleted to the parent of that node
            if activity_to_unlink.parent_id:
                for child in activity_to_unlink.child_ids:
                    child.write({
                        'parent_id': activity_to_unlink.parent_id.id,
                    })
            else:
                for child in activity_to_unlink.child_ids:
                    child.write({
                        'parent_id': False,
                        'trigger_type': activity_to_unlink.trigger_type
                            if child.trigger_type == 'activity' else child.trigger_type
                    })

        self.unlink()

    def _has_delay_node(self):
        return bool(self.interval_number)

    def _has_trigger_node(self):
        return self.activity_type != 'split' and self.trigger_type not in ['activity', 'begin', 'collect_reply']

    def _has_activity_node(self):
        return self.activity_type != 'structure'
