import Modeler from 'bpmn-js/lib/Modeler';
import NavigatedViewer from 'bpmn-js/lib/NavigatedViewer';
import { layoutProcess } from 'bpmn-auto-layout';
import { CreateAppendAnythingModule } from 'bpmn-js-create-append-anything';
import ColorPickerModule from 'bpmn-js-color-picker';
import MinimapModule from 'diagram-js-minimap';
import GridModule from 'diagram-js-grid';
import { Writer } from 'moddle-xml';
import odooModdle from './odoo_moddle.json';
import odooStyleModdle from './odoo_style_moddle.json';
import { OdooModelerUxModule, OdooViewerUxModule } from './odoo_ux.js';

window.OdooBpmn = {
  Modeler,
  NavigatedViewer,
  layoutProcess,
  // synchronous serialization (saveXML is async): needed when the page is closing
  toXMLSync: (definitions) => new Writer({ format: true, preamble: true }).toXML(definitions),
  odooModdle,
  odooStyleModdle,
  modelerModules: [CreateAppendAnythingModule, ColorPickerModule, MinimapModule, GridModule,
    OdooModelerUxModule],
  viewerModules: [MinimapModule, OdooViewerUxModule],
  version: '18.30.0',
};
