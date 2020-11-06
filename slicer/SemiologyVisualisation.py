import base64
import hashlib
import time
import logging
import warnings
from typing import Dict
from pathlib import Path
from abc import ABC, abstractmethod
from contextlib import contextmanager

import numpy as np
import SimpleITK as sitk

import vtk
import qt
import ctk
import slicer
import sitkUtils as su
from slicer.ScriptedLoadableModule import (
    ScriptedLoadableModule,
    ScriptedLoadableModuleWidget,
    ScriptedLoadableModuleLogic,
    ScriptedLoadableModuleTest,
)


BLACK = 0, 0, 0
VERY_DARK_GRAY = 0.15, 0.15, 0.15
DARK_GRAY = 0.25, 0.25, 0.25
GRAY = 0.5, 0.5, 0.5
LIGHT_GRAY = 0.75, 0.75, 0.75
WHITE = 1, 1, 1
LEFT = 'Left'
RIGHT = 'Right'
OTHER = 'Other'

IMAGE_FILE_STEM = 'MNI_152'
# IMAGE_FILE_STEM = 'colin27_t1_tal_lin'

ALIGN_ARGS = 1, 1, qt.Qt.AlignCenter

COLORMAPS = [
    'Cividis',
    'Plasma',
    'Viridis',
    'Magma',
    'Inferno',
    'Grey',
    'Red',
    'Green',
    'Blue',
    'Yellow',
    'Cyan',
    'Magenta',
]


class SemiologyVisualisation(ScriptedLoadableModule):

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "Semiology Visualisation"
        self.parent.categories = ["Epilepsy Semiology"]
        self.parent.dependencies = []
        self.parent.contributors = [
            "Fernando Perez-Garcia",
            "Ali Alim-Marvasti",
            "Gloria Romagnoli",
            "John S. Duncan",
        ]
        self.parent.helpText = """[This is the help text.]
    """
        self.parent.helpText += self.getDefaultModuleDocumentationLink()
        self.parent.acknowledgementText = """
    University College London.
    """

    def getDefaultModuleDocumentationLink(self):
        repoUrl = 'https://github.com/thenineteen/Semiology-Visualisation-Tool'
        linkText = f'See <a href="{repoUrl}">the documentation</a> for more information.'
        return linkText


class SemiologyVisualisationWidget(ScriptedLoadableModuleWidget):

    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)
        self.logic = SemiologyVisualisationLogic()
        self.logic.installRepository()
        self.parcellation = GIFParcellation(
            segmentationPath=self.logic.getGifSegmentationPath(),
            colorTablePath=self.logic.getGifTablePath(),
        )
        self.makeGUI()
        self.scoresVolumeNode = None
        self.parcellationLabelMapNode = None
        self.tableNode = None
        self.customSemiologies = []
        slicer.semiologyVisualisation = self

    def makeGUI(self):
        self.makeLoadDataButton()
        self.makeSettingsButton()
        self.makeUpdateButton()
        self.makeTableButton()

        # self.semiologiesTableSplitter = qt.QSplitter()
        # self.semiologiesTableSplitter.setOrientation(qt.Qt.Vertical)
        # self.layout.addWidget(self.semiologiesTableSplitter)
        # self.semiologiesTableSplitter.addWidget(self.settingsCollapsibleButton)
        # self.semiologiesTableSplitter.addWidget(self.updateButton)

        # Add vertical spacer

    def makeSettingsButton(self):
        self.settingsCollapsibleButton = ctk.ctkCollapsibleButton()
        self.settingsCollapsibleButton.hide()
        self.settingsCollapsibleButton.text = 'Settings'

        self.settingsLayout = qt.QVBoxLayout(self.settingsCollapsibleButton)

        self.settingsTabWidget = qt.QTabWidget()
        self.settingsLayout.addWidget(self.settingsTabWidget)

        patientQueryTab = self.getPatientQueryTab()
        databaseTab = self.getDatabaseTab()
        visualisationTab = self.getVisualisationSettingsTab()
        advancedTab = self.getAdvancedSettingsTab()

        self.settingsTabWidget.addTab(patientQueryTab, 'Patient query')
        self.settingsTabWidget.addTab(databaseTab, 'Database')
        self.settingsTabWidget.addTab(visualisationTab, 'Visualisation')
        self.settingsTabWidget.addTab(advancedTab, 'Advanced')

        self.layout.addWidget(self.settingsCollapsibleButton)

    def getPatientQueryTab(self):
        patientQueryTabWidget = qt.QWidget()
        patientQueryLayout = qt.QVBoxLayout(patientQueryTabWidget)

        dominantHemisphereLayout = qt.QHBoxLayout()
        patientQueryLayout.addLayout(self.getDominantHemisphereLayout())

        semiologiesGroupBox = qt.QGroupBox('Semiologies')
        semiologiesGroupBox.setLayout(self.getSemiologiesLayout())
        patientQueryLayout.addWidget(semiologiesGroupBox)

        return patientQueryTabWidget

    def getInclusionsWidget(self):
        inclusionsGroupBox = qt.QGroupBox('Inclusions')
        inclusionsLayout = qt.QVBoxLayout(inclusionsGroupBox)

        ezgtGroupBox = qt.QGroupBox('Epileptogenic zone ground truth')
        inclusionsLayout.addWidget(ezgtGroupBox)
        ezgtLayout = qt.QVBoxLayout(ezgtGroupBox)

        self.postSurgicalSzFreedomCheckBox = qt.QCheckBox(
            'Postoperative seizure freedom')
        self.invasiveEegCheckBox = qt.QCheckBox('Invasive EEG monitoring')
        self.concordanceCheckBox = qt.QCheckBox('Multimodal concordance')

        self.postSurgicalSzFreedomCheckBox.setToolTip(
            'Engel Ia,b - ILAE 1,2 confirmed at a minimum follow-up of 12 months.'
            '\n\n'
            'When unticked, seizure-free cases are excluded if they are the only ground truth'
        )
        self.invasiveEegCheckBox.setToolTip(
            'Invasive EEG recording and/or electrical stimulation, mapping seizure semiology.'
            '\n\n'
            'When unticked, stereotactic EEG cases are excluded only if they are the only ground truth'
        )
        self.concordanceCheckBox.setToolTip(
            'Multimodal concordance between brain imaging and neurophysiology '
            '(e.g. PET, SPECT, MEG, EEG, fMRI, etc.) pointing towards a '
            'highly probable epileptogenic zone'
            '\n\n'
            'When unticked, concordant data are excluded only if they are the only ground truth'
        )

        self.postSurgicalSzFreedomCheckBox.setChecked(True)
        self.invasiveEegCheckBox.setChecked(True)
        self.concordanceCheckBox.setChecked(True)

        ezgtLayout.addWidget(self.postSurgicalSzFreedomCheckBox)
        ezgtLayout.addWidget(self.invasiveEegCheckBox)
        ezgtLayout.addWidget(self.concordanceCheckBox)

        publicationGroupBox = qt.QGroupBox('Publication approaches')
        inclusionsLayout.addWidget(publicationGroupBox)
        publicationLayout = qt.QVBoxLayout(publicationGroupBox)

        self.epilepsyTopologyCheckBox = qt.QCheckBox('Epilepsy topology')
        self.seizureSemiologyCheckBox = qt.QCheckBox('Seizure semiology')
        self.brainStimulationCheckBox = qt.QCheckBox('Cortical stimulation')

        self.epilepsyTopologyCheckBox.setToolTip(
            'When the paper pre-selects samples of patients based on their established epileptogenic zone '
            '(site of surgical resection) or seizure onset zone (neurophysiological/anatomical), and '
            'describes the related seizure semiology - e.g. articles looking at TLE, FLE, OLE. \n\n'
            'When unticked, ALL epilepsy topology data are excluded, EVEN if there are other approaches'
        )
        self.seizureSemiologyCheckBox.setToolTip(
            'When the paper pre-selects a sample of patients based on their seizure semiology '
            '(e.g. nose-wiping, gelastic, ictal kissing), or '
            'reports on a cohort of unselected patients with epilepsy, or '
            'pre-selects based on other non-topological factors (specific techniques or conditions e.g. FCD). \n\n'
            'When unticked, ALL spontaneous semiology cases are excluded, even if there are other approaches'
        )
        self.brainStimulationCheckBox.setToolTip(
            'When the paper describes the semiology elicited by electrical brain stimulation, '
            'in the context of pre- and/or intra-operative functional mapping. \n\n'
            'When unticked, electrical stimulation cases are only excluded if they are the ONLY ground truth'
        )

        self.epilepsyTopologyCheckBox.setChecked(True)
        self.seizureSemiologyCheckBox.setChecked(True)
        self.brainStimulationCheckBox.setChecked(True)

        publicationLayout.addWidget(self.epilepsyTopologyCheckBox)
        publicationLayout.addWidget(self.seizureSemiologyCheckBox)
        publicationLayout.addWidget(self.brainStimulationCheckBox)

        ageGroupBox = qt.QGroupBox('Age')
        inclusionsLayout.addWidget(ageGroupBox)
        ageLayout = qt.QVBoxLayout(ageGroupBox)
        self.paediatricCheckBox = qt.QCheckBox(
            'Only paediatric under seven years')
        self.paediatricCheckBox.setToolTip(
            'Include only cases for which we are certain that the semiology was'
            ' reported in a patient under 7-years old. If unchecked, this cases will'
            ' be excluded.'
        )
        ageLayout.addWidget(self.paediatricCheckBox)

        self.postSurgicalSzFreedomCheckBox = qt.QCheckBox(
            'Postoperative seizure freedom')

        return inclusionsGroupBox

    def getDatabaseTab(self):
        dataBaseTabWidget = qt.QWidget()
        dataBaseTabLayout = qt.QVBoxLayout(dataBaseTabWidget)

        inclusionsGroupBox = self.getInclusionsWidget()
        dataBaseTabLayout.addWidget(inclusionsGroupBox)

        self.granularCheckBox = qt.QCheckBox(
            'Granular as reported (non postcode)')
        self.granularCheckBox.setChecked(True)
        self.granularCheckBox.toggled.connect(self.onGranularCheckBox)
        dataBaseTabLayout.addWidget(self.granularCheckBox)

        self.inverseLocalisingCheckBox = qt.QCheckBox(
            'Use inverse localising spread values')
        self.inverseLocalisingCheckBox.setToolTip(
            'Reduce the localising-values in the Semio2Brain database in a way'
            ' inversely proportional to the number of brain regions to which the'
            ' semiology of interest localised.'
            ' This option provides an inverse variance weighting relative to'
            ' the spread of localisation, favouring semiologies which are more'
            ' (uni)-focal.'
            ' This option is only available when using the "granular postcode'
            ' hierarchy reversal" option.'
        )
        dataBaseTabLayout.addWidget(self.inverseLocalisingCheckBox)

        return dataBaseTabWidget

    def getVisualisationSettingsTab(self):
        visualisationSettingsWidget = qt.QWidget()
        visualisationSettingsLayout = qt.QFormLayout(
            visualisationSettingsWidget)
        visualisationSettingsLayout.addWidget(self.getShowGIFButton())
        visualisationSettingsLayout.addRow(
            'Show hemispheres: ', self.getHemispheresVisibleLayout())
        self.segmentsComboBox = self.getGoToStructureWidget()
        self.segmentsComboBox.currentIndexChanged.connect(
            self.onSegmentsComboBox)
        visualisationSettingsLayout.addRow(
            'Jump to structure: ', self.segmentsComboBox)

        self.showProgressCheckBox = qt.QCheckBox(
            'Show progress when updating colours')
        self.showProgressCheckBox.setChecked(True)
        visualisationSettingsLayout.addWidget(self.showProgressCheckBox)

        self.min2dOpacitySlider = slicer.qMRMLSliderWidget()
        self.min2dOpacitySlider.maximum = 1
        self.min2dOpacitySlider.singleStep = 0.01
        self.min2dOpacitySlider.value = 0.25
        visualisationSettingsLayout.addRow(
            'Min. 2D opacity: ',
            self.min2dOpacitySlider,
        )

        self.colorBlindCheckbox = qt.QCheckBox('Colour-blind mode')
        self.colorBlindCheckbox.toggled.connect(self.onColorBlindCheckBox)
        visualisationSettingsLayout.addWidget(self.colorBlindCheckbox)

        self.colorSelector = self.getColorsButton()
        visualisationSettingsLayout.addRow(
            'Colour map: ',
            self.colorSelector,
        )

        self.autoUpdateCheckBox = qt.QCheckBox('Auto-update')
        self.autoUpdateCheckBox.setChecked(False)
        self.autoUpdateCheckBox.toggled.connect(self.onAutoUpdateCheckBox)
        visualisationSettingsLayout.addWidget(self.autoUpdateCheckBox)

        return visualisationSettingsWidget

    def getGoToStructureWidget(self):
        from mega_analysis import gif_lobes_from_excel_sheets
        lobesToLabels = gif_lobes_from_excel_sheets()
        self.gifComboBoxItemsToLabels = {}
        for key, labels in lobesToLabels.items():
            lobe = key.split()[1]
            for label in labels:
                structureName = self.parcellation.getNameFromLabel(label)
                item = f'{lobe} - {structureName}'
                self.gifComboBoxItemsToLabels[item] = structureName
        widget = qt.QComboBox()
        widget.addItems(list(self.gifComboBoxItemsToLabels.keys()))
        return widget

    def getDominantHemisphereLayout(self):
        self.leftDominantRadioButton = qt.QRadioButton('Left')
        self.rightDominantRadioButton = qt.QRadioButton('Right')
        self.unknownDominantRadioButton = qt.QRadioButton('Unknown')
        self.leftDominantRadioButton.setChecked(True)
        dominantHemisphereLayout = qt.QHBoxLayout()
        dominantHemisphereLayout.addWidget(qt.QLabel('Dominant hemisphere: '))
        dominantHemisphereLayout.addWidget(self.leftDominantRadioButton)
        dominantHemisphereLayout.addWidget(self.rightDominantRadioButton)
        dominantHemisphereLayout.addWidget(self.unknownDominantRadioButton)
        self.leftDominantRadioButton.toggled.connect(self.onAutoUpdateButton)
        self.rightDominantRadioButton.toggled.connect(self.onAutoUpdateButton)
        self.unknownDominantRadioButton.toggled.connect(
            self.onAutoUpdateButton)
        return dominantHemisphereLayout

    def getSemiologiesLayout(self):
        semiologiesFormLayout = qt.QFormLayout()
        semiologiesScrollArea = self.getSemiologiesScrollArea()
        self.semiologiesWidget = semiologiesScrollArea.widget()
        semiologiesFormLayout.addWidget(semiologiesScrollArea)

        self.removeLineEditButton = qt.QPushButton('Remove custom semiology')
        self.removeLineEditButton.setDisabled(True)
        self.removeLineEditButton.clicked.connect(self.removeCustomSemiology)
        addLineEditButton = qt.QPushButton('Add custom semiology')
        addLineEditButton.clicked.connect(self.addCustomSemiology)

        self.deselectAllButton = qt.QPushButton('Deselect all')
        self.deselectAllButton.clicked.connect(self.unselectAllSemiologies)

        customSemiologiesFrame = qt.QFrame()
        customSemiologiesLayout = qt.QHBoxLayout(customSemiologiesFrame)
        customSemiologiesLayout.addWidget(self.deselectAllButton)
        customSemiologiesLayout.addWidget(self.removeLineEditButton)
        customSemiologiesLayout.addWidget(addLineEditButton)
        semiologiesFormLayout.addWidget(customSemiologiesFrame)
        return semiologiesFormLayout

    def getAdvancedSettingsTab(self):
        advancedTabWidget = qt.QWidget()
        advancedTabLayout = qt.QVBoxLayout(advancedTabWidget)

        # Cache
        cacheGroupBox = qt.QGroupBox('Cache')
        advancedTabLayout.addWidget(cacheGroupBox)
        cacheLayout = qt.QVBoxLayout(cacheGroupBox)

        self.useCacheCheckBox = qt.QCheckBox('Use cached queries if available')
        self.useCacheCheckBox.setChecked(False)
        cacheLayout.addWidget(self.useCacheCheckBox)

        self.clearCacheButton = qt.QPushButton('Clear cache')
        self.clearCacheButton.clicked.connect(self.logic.clearCache)
        cacheLayout.addWidget(self.clearCacheButton)

        # Normalisation
        normalisationGroupBox = qt.QGroupBox('Normalisation function')
        advancedTabLayout.addWidget(normalisationGroupBox)
        normalisationLayout = qt.QHBoxLayout(normalisationGroupBox)

        self.minmaxRadioButton = qt.QRadioButton('Rescaling')
        normalisationLayout.addWidget(self.minmaxRadioButton)

        self.softmaxRadioButton = qt.QRadioButton('Softmax')
        normalisationLayout.addWidget(self.softmaxRadioButton)

        self.proportionsRadioButton = qt.QRadioButton('Proportions')
        self.proportionsRadioButton.setChecked(True)
        normalisationLayout.addWidget(self.proportionsRadioButton)

        return advancedTabWidget

    def makeTableButton(self):
        self.tableCollapsibleButton = ctk.ctkCollapsibleButton()
        self.tableCollapsibleButton.visible = False
        self.tableCollapsibleButton.text = 'Scores'

        self.layout.addWidget(self.tableCollapsibleButton)

        tableLayout = qt.QFormLayout(self.tableCollapsibleButton)
        self.tableView = slicer.qMRMLTableView()
        tableLayout.addWidget(self.tableView)

    def makeLoadDataButton(self):
        self.loadDataButton = qt.QPushButton('Load data')
        self.loadDataButton.setStyleSheet('font: bold')
        self.loadDataButton.clicked.connect(self.onLoadDataButton)
        self.layout.addWidget(self.loadDataButton)

    def getColorsButton(self):
        colorSelector = slicer.qMRMLColorTableComboBox()
        colorSelector.nodeTypes = ["vtkMRMLColorNode"]
        colorSelector.hideChildNodeTypes = (
            "vtkMRMLDiffusionTensorDisplayPropertiesNode",
            "vtkMRMLProceduralColorNode",
        )
        colorSelector.addEnabled = False
        colorSelector.removeEnabled = False
        colorSelector.noneEnabled = False
        colorSelector.selectNodeUponCreation = True
        colorSelector.showHidden = True
        colorSelector.showChildNodeTypes = True
        colorSelector.setMRMLScene(slicer.mrmlScene)
        colorSelector.setToolTip("Choose a colormap")
        colorSelector.currentNodeID = 'vtkMRMLColorTableNodeFileViridis.txt'
        colorSelector.currentNodeChanged.connect(self.onAutoUpdateButton)
        self.logic.removeColorMaps()
        return colorSelector

    def getShowGIFButton(self):
        self.showGifButton = qt.QPushButton('Show GIF colors')
        self.showGifButton.clicked.connect(self.onshowGifButton)
        return self.showGifButton

    def getHemispheresVisibleLayout(self):
        self.showLeftHemisphereCheckBox = qt.QCheckBox('Left')
        self.showRightHemisphereCheckBox = qt.QCheckBox('Right')
        self.showLeftHemisphereCheckBox.setChecked(True)
        self.showRightHemisphereCheckBox.setChecked(True)
        showHemispheresLayout = qt.QHBoxLayout()
        showHemispheresLayout.addWidget(self.showLeftHemisphereCheckBox)
        showHemispheresLayout.addWidget(self.showRightHemisphereCheckBox)
        self.showLeftHemisphereCheckBox.toggled.connect(
            self.onAutoUpdateButton)
        self.showRightHemisphereCheckBox.toggled.connect(
            self.onAutoUpdateButton)
        return showHemispheresLayout

    def makeUpdateButton(self):
        self.updateButton = qt.QPushButton('Update visualisation')
        self.updateButton.setStyleSheet('font: bold')
        self.updateButton.hide()
        self.updateButton.enabled = not self.autoUpdateCheckBox.isChecked()
        self.updateButton.clicked.connect(self.updateColors)
        self.layout.addWidget(self.updateButton)

    def getSemiologiesScrollArea(self):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from mega_analysis import (
                    get_all_semiology_terms,
                    get_possible_lateralities,
                )
        except ImportError as e:
            message = f'{e}\n\nPlease restart 3D Slicer and try again'
            slicer.util.errorDisplay(message)

        lateralitiesDict = {
            term: get_possible_lateralities(term)
            for term in get_all_semiology_terms()
        }
        self.semiologiesWidgetsDict = self.logic.getSemiologiesWidgetsDict(
            lateralitiesDict,
            self.onAutoUpdateButton,
            self.onSemiologyCheckBox,
        )
        semiologiesWidget = qt.QWidget()
        semiologiesLayout = qt.QGridLayout(semiologiesWidget)
        iterable = enumerate(self.semiologiesWidgetsDict.items())
        for row, (semiology, widgetsDict) in iterable:
            semiologiesLayout.addWidget(widgetsDict['checkBox'], row, 0)
            for i, laterality in enumerate(('left', 'right', 'other')):
                widget = widgetsDict[f'{laterality}RadioButton']
                if widget is not None:
                    semiologiesLayout.addWidget(
                        widget, row, i + 1, *ALIGN_ARGS)

        # https://www.learnpyqt.com/courses/adanced-ui-features/qscrollarea/
        scrollArea = qt.QScrollArea()
        scrollArea.setVerticalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOn)
        scrollArea.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        scrollArea.setWidgetResizable(True)
        scrollArea.setWidget(semiologiesWidget)

        return scrollArea

    def getColorNode(self):
        if self.colorBlindCheckbox.isChecked():
            colorNode = slicer.util.getFirstNodeByClassByName(
                'vtkMRMLColorTableNode',
                'Cividis',
            )
        else:
            colorNode = self.colorSelector.currentNode()
        return colorNode

    def getSemiologyTermsAndSidesFromGUI(self):
        from mega_analysis.semiology import Laterality
        lateralitiesDict = {
            'left': Laterality.LEFT,
            'right': Laterality.RIGHT,
            'other': Laterality.NEUTRAL,
        }
        termsAndSides = []
        for (semiologyTerm, widgetsDict) in self.semiologiesWidgetsDict.items():
            if not widgetsDict['checkBox'].isChecked():
                continue
            for lateralityName, laterality in lateralitiesDict.items():
                widget = widgetsDict[f'{lateralityName}RadioButton']
                if widget is not None and widget.isChecked():
                    result = semiologyTerm, laterality
                    termsAndSides.append(result)
                    break
            else:
                message = f'Please select a laterality for semiology term "{semiologyTerm}"'
                slicer.util.errorDisplay(message)
                raise ValueError(message)

        for customSemiology in self.customSemiologies:
            if not customSemiology.isChecked():
                continue
            semiologyTerm = customSemiology.term
            laterality = customSemiology.laterality
            if laterality is None:
                message = f'Please select a laterality for custom semiology term "{semiologyTerm}"'
                slicer.util.errorDisplay(message)
                raise ValueError(message)
            termsAndSides.append((semiologyTerm, laterality))
        termsAndSides = None if not termsAndSides else termsAndSides
        return termsAndSides

    def getSemiologiesListFromGUI(self):
        from mega_analysis.semiology import Semiology
        termsAndSides = self.getSemiologyTermsAndSidesFromGUI()
        if termsAndSides is None:
            slicer.util.messageBox(
                'Please select at least one semiology and laterality')
            return
        semiologies = []
        for semiologyTerm, symptomsSide in termsAndSides:
            semiology = Semiology(
                semiologyTerm,
                symptomsSide,
                self.getDominantHemisphereFromGUI(),
                granular=self.granularCheckBox.isChecked(),
                include_seizure_freedom=self.seizureSemiologyCheckBox.isChecked(),
                include_concordance=self.concordanceCheckBox.isChecked(),
                include_seeg=self.invasiveEegCheckBox.isChecked(),
                include_cortical_stimulation=self.brainStimulationCheckBox.isChecked(),
                include_et_topology_ez=self.epilepsyTopologyCheckBox.isChecked(),
                include_spontaneous_semiology=self.seizureSemiologyCheckBox.isChecked(),
                include_only_paediatric_cases=self.paediatricCheckBox.isChecked(),
                inverse_localising_values=self.inverseLocalisingCheckBox.isChecked(),
            )
            semiologies.append(semiology)
        return semiologies

    def getSemiologiesDataFrameFromGUI(self):
        semiologies = self.getSemiologiesListFromGUI()
        if semiologies is None:  # No semiologies selected
            return
        return self.getScoresFromCache(semiologies)

    def getScoresFromCache(self, semiologies):
        from mega_analysis.semiology import get_df_from_semiologies
        cache = self.logic.readCache()
        query = Query(semiologies)
        hashedQuery = query.hash()
        if hashedQuery in cache and self.useCacheCheckBox.isChecked():
            logging.info(f'Query found in cache: {hashedQuery}')
            scores = Scores(cache[hashedQuery])
            dataFrame = scores.df
        else:
            with messageContextManager('Querying mega_analysis module...'):
                try:
                    if self.minmaxRadioButton.isChecked():
                        method = 'minmax'
                    elif self.softmaxRadioButton.isChecked():
                        method = 'softmax'
                    elif self.proportionsRadioButton.isChecked():
                        method = 'proportions'
                    dataFrame = get_df_from_semiologies(semiologies, method=method)
                    scores = Scores(dataFrame)
                    cache[hashedQuery] = scores.toDict()
                    self.logic.writeCache(cache)
                except Exception as e:
                    message = (
                        'Error retrieving semiology information from mega_analysis module.'
                        f' Details:\n\n{e}\n\n'
                        'If you think this is a bug, please report this issue on the repository:'
                        ' https://github.com/thenineteen/Semiology-Visualisation-Tool/issues/new'
                    )
                    slicer.util.errorDisplay(message)
                    dataFrame = None
                    raise
        return dataFrame

    def getDominantHemisphereFromGUI(self):
        from mega_analysis.semiology import Laterality
        if self.leftDominantRadioButton.isChecked():
            return Laterality.LEFT
        if self.rightDominantRadioButton.isChecked():
            return Laterality.RIGHT
        if self.unknownDominantRadioButton.isChecked():
            return Laterality.NEUTRAL

    # Currently unused
    def addGifStructuresToComboBox(self):
        structures = self.parcellation.getSegmentIDs()
        labels = [
            int(self.parcellation.getLabelFromName(name)) for name in structures
        ]
        names = []
        for label, structure in zip(labels, structures):
            split = structure.split('-')
            if label < 100:
                name = f'{label} - {" ".join(split)}'
            else:
                name = f'{label} - {" ".join(split[:2])} ({" ".join(split[2:])})'
            names.append(name)
        self.segmentsComboBox.addItems(names)
        # temporarily, until logic is implemented
        self.segmentsComboBox.setEnabled(False)

    # Slots
    def onSemiologyCheckBox(self):
        for widgetsDict in self.semiologiesWidgetsDict.values():
            enable = widgetsDict['checkBox'].isChecked()

            # If lateralities shouldn't be available, don't show only "Other" radio button
            if widgetsDict[f'leftRadioButton'] is None:
                continue

            for i, laterality in enumerate(('left', 'right', 'other')):
                widget = widgetsDict[f'{laterality}RadioButton']
                if widget is not None:
                    widget.setVisible(enable)
        self.onAutoUpdateButton()

    def onAutoUpdateButton(self):
        try:
            if self.autoUpdateCheckBox.isChecked():
                self.updateColors()
        except AttributeError:
            # autoUpdateCheckBox not created yet
            pass

    def onshowGifButton(self):
        self.parcellation.setOriginalColors(
            showProgress=self.showProgressCheckBox.isChecked())

    def onSelect(self):
        # parcellationPath = Path(self.parcellationPathEdit.currentPath)
        # referencePath = Path(self.referencePathEdit.currentPath)
        # parcellationIsFile = parcellationPath.is_file()
        # referenceIsFile = referencePath.is_file()
        # if not parcellationIsFile:
        #   print(parcellationIsFile, 'does not exist')
        # if not referenceIsFile:
        #   print(referenceIsFile, 'does not exist')
        # self.applyButton.enabled = parcellationIsFile and referenceIsFile

        scoresPath = Path(self.scoresPathEdit.currentPath)
        scoresIsFile = scoresPath.is_file()
        if not scoresIsFile:
            print(scoresIsFile, 'does not exist')
        self.applyButton.enabled = scoresIsFile

    def onLoadDataButton(self):
        self.referenceVolumeNode = self.logic.loadVolume(
            self.logic.getDefaultReferencePath())
        self.parcellationLabelMapNode = self.logic.loadParcellation(
            self.logic.getDefaultParcellationPath())
        slicer.util.setSliceViewerLayers(
            label=None,
        )
        self.parcellation.load()
        # self.addGifStructuresToComboBox()
        self.settingsCollapsibleButton.show()
        self.updateButton.show()
        self.loadDataButton.hide()

    def onAutoUpdateCheckBox(self):
        self.updateButton.setDisabled(self.autoUpdateCheckBox.isChecked())

    def updateColors(self):
        from mega_analysis.semiology import (
            normalise_semiologies_df,
            combine_semiologies_df,
        )

        colorNode = self.getColorNode()
        if colorNode is None:
            slicer.util.errorDisplay('No color node is selected')
            return

        semiologiesDataFrame = self.getSemiologiesDataFrameFromGUI()
        normalise = True  # len(semiologiesDataFrame) > 1
        if normalise:
            if self.minmaxRadioButton.isChecked():
                method = 'minmax'
            elif self.softmaxRadioButton.isChecked():
                method = 'softmax'
            elif self.proportionsRadioButton.isChecked():
                method = 'proportions'
            normalisedDataFrame = normalise_semiologies_df(
                semiologiesDataFrame,
                method=method,
            )
            combinedDataFrame = combine_semiologies_df(
                normalisedDataFrame, method=method, normalise=True)
        else:
            combinedDataFrame = combine_semiologies_df(
                semiologiesDataFrame, method=method, normalise=False)

        if self.logic.dataFrameIsEmpty(combinedDataFrame):
            slicer.util.errorDisplay('The combined results are empty')
            return

        scoresDict = dict(combinedDataFrame.iloc[0])
        if scoresDict is None:
            return
        self.scoresVolumeNode = self.logic.getScoresVolumeNode(
            scoresDict,
            colorNode,
            self.parcellationLabelMapNode,
            self.scoresVolumeNode,
        )
        showLeft = self.showLeftHemisphereCheckBox.isChecked()
        showRight = self.showRightHemisphereCheckBox.isChecked()
        self.parcellation.setScoresColors(
            scoresDict,
            colorNode,
            BLACK if self.colorBlindCheckbox.isChecked() else LIGHT_GRAY,
            showLeft=showLeft,
            showRight=showRight,
            showProgress=self.showProgressCheckBox.isChecked(),
            min2dOpacity=self.min2dOpacitySlider.value,
        )

        with messageContextManager('Showing volumes on 2D slices...'):
            slicer.util.setSliceViewerLayers(
                foreground=self.scoresVolumeNode,
                foregroundOpacity=0,
                labelOpacity=0,
            )
        with messageContextManager('Disabling interpolation for scores volume node...'):
            self.scoresVolumeNode.GetDisplayNode().SetInterpolate(False)
        with messageContextManager('Showing scalar bar...'):
            self.logic.showForegroundScalarBar()
        with messageContextManager('Jumping to structure with highest score...'):
            self.logic.jumpToMax(self.scoresVolumeNode)

        with messageContextManager('Creating data points table...'):
            self.parcellation.useNamesForDataFramesColumns(
                semiologiesDataFrame,
                combinedDataFrame,
            )
            stringsDataFrame = self.logic.getStringsDataFrame(
                semiologiesDataFrame,
                combinedDataFrame,
            )
            self.tableNode = self.logic.dataFrameToTable(
                stringsDataFrame.T,
                self.tableNode,
            )
            self.tableCollapsibleButton.visible = True
            self.logic.showTableInModuleLayout(self.tableView, self.tableNode)
            # self.logic.showTableInViewLayout(self.tableNode)

        self.settingsCollapsibleButton.setChecked(False)
        self.tableCollapsibleButton.setChecked(True)

    def onColorBlindCheckBox(self):
        self.colorSelector.setDisabled(self.colorBlindCheckbox.isChecked())
        self.onAutoUpdateButton()

    def getCustomSemiologyTermFromUser(self):
        return self.logic.getCustomSemiologyTermFromDialog()

    def addCustomSemiology(self, term=None):
        if not term or term is None:
            term = self.getCustomSemiologyTermFromUser()
            if term is None:
                return
        customSemiology = CustomSemiology(term)
        gridLayout = self.semiologiesWidget.layout()
        numRows = gridLayout.rowCount()
        gridLayout.addWidget(customSemiology.checkBox, numRows, 0)
        for i, radioButton in enumerate(customSemiology.radioButtons.values(), start=1):
            gridLayout.addWidget(radioButton, numRows, i, *ALIGN_ARGS)
        self.customSemiologies.append(customSemiology)
        self.removeLineEditButton.setEnabled(True)

    def removeCustomSemiology(self):
        customSemiology = self.customSemiologies.pop()
        for widget in customSemiology.widgets:
            widget.hide()
            self.semiologiesWidget.layout().removeWidget(widget)
        del customSemiology
        self.removeLineEditButton.setEnabled(self.customSemiologies)

    def unselectAllSemiologies(self):
        for widgetsDict in self.semiologiesWidgetsDict.values():
            checkBox = widgetsDict['checkBox']
            checkBox.setChecked(False)
        for customSemiology in self.customSemiologies:
            customSemiology.unCheck()

    def onSegmentsComboBox(self):
        name = self.gifComboBoxItemsToLabels[self.segmentsComboBox.currentText]
        self.parcellation.jumpToStructure(name)

    def onGranularCheckBox(self):
        if self.granularCheckBox.isChecked():
            self.inverseLocalisingCheckBox.setEnabled(True)
        else:
            self.inverseLocalisingCheckBox.setChecked(False)
            self.inverseLocalisingCheckBox.setEnabled(False)


class SemiologyVisualisationLogic(ScriptedLoadableModuleLogic):

    def getSemiologiesWidgetsDict(
        self,
        lateralitiesDict,
        radioButtonSlot,
        checkBoxSlot,
    ):
        from mega_analysis import Laterality
        semiologiesDict = {}
        for semiology_term, lateralities in lateralitiesDict.items():
            checkBox = qt.QCheckBox(semiology_term)
            checkBox.toggled.connect(checkBoxSlot)
            buttonGroup = qt.QButtonGroup()

            leftRadioButton = qt.QRadioButton('Left')
            leftRadioButton.clicked.connect(radioButtonSlot)
            leftRadioButton.hide()
            buttonGroup.addButton(leftRadioButton)

            rightRadioButton = qt.QRadioButton('Right')
            rightRadioButton.clicked.connect(radioButtonSlot)
            rightRadioButton.hide()
            buttonGroup.addButton(rightRadioButton)

            otherRadioButton = qt.QRadioButton('Other')
            otherRadioButton.clicked.connect(radioButtonSlot)
            otherRadioButton.hide()
            buttonGroup.addButton(otherRadioButton)

            if len(lateralities) == 1 and lateralities[0] == Laterality.NEUTRAL:
                otherRadioButton.setChecked(True)

            semiologiesDict[semiology_term] = dict(
                checkBox=checkBox,
                leftRadioButton=leftRadioButton if Laterality.LEFT in lateralities else None,
                rightRadioButton=rightRadioButton if Laterality.RIGHT in lateralities else None,
                otherRadioButton=otherRadioButton if Laterality.NEUTRAL in lateralities else None,
                buttonGroup=buttonGroup,
            )
        return semiologiesDict

    def loadVolume(self, imagePath):
        stem = Path(imagePath).name.split('.')[0]
        try:
            volumeNode = slicer.util.getNode(stem)
        except slicer.util.MRMLNodeNotFoundException:
            volumeNode = slicer.util.loadVolume(str(imagePath))
        return volumeNode

    def loadParcellation(self, imagePath, gifVersion=None):
        stem = Path(imagePath).name.split('.')[0]
        try:
            volumeNode = slicer.util.getNode(stem)
        except Exception as e:  # slicer.util.MRMLNodeNotFoundException:
            print(e)
            volumeNode = slicer.util.loadLabelVolume(str(imagePath))
            colorNode = self.getGifColorNode(version=gifVersion)
            displayNode = volumeNode.GetDisplayNode()
            displayNode.SetAndObserveColorNodeID(colorNode.GetID())
        return volumeNode

    def getGifTablePath(self, version=None):
        version = 3 if version is None else version
        colorDir = self.getResourcesDir() / 'Color'
        filename = f'BrainAnatomyLabelsV{version}_0.txt'
        colorPath = colorDir / filename
        return colorPath

    def getGifSegmentationPath(self):
        return self.getImagesDir() / f'{IMAGE_FILE_STEM}_gif_cerebrum.seg.nrrd'

    def getGifColorNode(self, version=None):
        colorPath = self.getGifTablePath(version=version)
        colorNodeName = colorPath.stem
        className = 'vtkMRMLColorTableNode'
        colorNode = slicer.util.getFirstNodeByClassByName(
            className, colorNodeName)
        if colorNode is None:
            colorNode = slicer.util.loadColorTable(str(colorPath))
        return colorNode

    def getGifSegmentationNode(self):
        return slicer.util.loadSegmentation(str(self.getGifSegmentationPath()))

    def getResourcesDir(self):
        moduleDir = Path(slicer.util.modulePath(self.moduleName)).parent
        resourcesDir = moduleDir / 'Resources'
        return resourcesDir

    def getImagesDir(self):
        return self.getResourcesDir() / 'Image'

    def getDefaultReferencePath(self):
        return self.getImagesDir() / f'{IMAGE_FILE_STEM}_mri.nii.gz'

    def getDefaultParcellationPath(self):
        return self.getImagesDir() / f'{IMAGE_FILE_STEM}_gif.nii.gz'

    def getScoresVolumeNode(
        self,
        scoresDict,
        colorNode,
        parcellationLabelMapNode,
        outputNode,
        showProgress=True,
    ):
        """Create a scalar volume node so that the colorbar is correct."""

        with messageContextManager('Creating scores volume node...'):
            parcellationImage = su.PullVolumeFromSlicer(
                parcellationLabelMapNode)
            parcellationArray = sitk.GetArrayViewFromImage(parcellationImage)
            scoresArray = np.zeros_like(parcellationArray, np.float)

            if scoresDict is not None:
                numSegments = len(scoresDict)
                if showProgress:
                    progressDialog = slicer.util.createProgressDialog(
                        value=0,
                        maximum=numSegments,
                        windowTitle='Creating scores volume node...',
                    )
                for i, (label, score) in enumerate(scoresDict.items()):
                    if showProgress:
                        progressDialog.setValue(i)
                        slicer.app.processEvents()
                    label = int(label)
                    score = float(score)
                    labelMask = parcellationArray == label
                    scoresArray[labelMask] = score
                if showProgress:
                    progressDialog.setValue(numSegments)
                    slicer.app.processEvents()
                    progressDialog.close()

            scoresImage = self.getImageFromArray(
                scoresArray, parcellationImage)
            scoresName = 'Scores'
            scoresVolumeNode = su.PushVolumeToSlicer(
                scoresImage,
                name=scoresName,
                targetNode=outputNode,
            )
            displayNode = scoresVolumeNode.GetDisplayNode()
            displayNode.SetAutoThreshold(False)
            displayNode.SetAndObserveColorNodeID(colorNode.GetID())
            displayNode.SetLowerThreshold(1)
            displayNode.ApplyThresholdOn()
            displayNode.SetAutoWindowLevel(False)
            windowMin = scoresArray[scoresArray >
                                    0].min() if scoresArray.any() else 0
            windowMax = scoresArray.max()
            displayNode.SetWindowLevelMinMax(windowMin, windowMax)

        return scoresVolumeNode

    def getImageFromArray(self, array, referenceImage):
        image = sitk.GetImageFromArray(array)
        image.SetDirection(referenceImage.GetDirection())
        image.SetOrigin(referenceImage.GetOrigin())
        image.SetSpacing(referenceImage.GetSpacing())
        return image

    def removeColorMaps(self):
        for colorNode in slicer.util.getNodesByClass('vtkMRMLColorNode'):
            if colorNode.GetName() not in COLORMAPS:
                slicer.mrmlScene.RemoveNode(colorNode)

    def getPythonConsoleWidget(self):
        return slicer.util.mainWindow().pythonConsole().parent()

    def installRepository(self):
        repoDir = Path(__file__).parent.parent
        import sys
        sys.path.insert(0, str(repoDir))
        with messageContextManager('Importing mega_analysis Python module...'):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    import mega_analysis
            except ImportError:
                requirementsPath = repoDir / 'requirements.txt'
                console = self.getPythonConsoleWidget()
                pythonVisible = console.visible
                console.setVisible(True)
                slicer.util.pip_install(
                    f'-r {requirementsPath}'
                )
                console.setVisible(pythonVisible)
            import matplotlib
            matplotlib.use('agg')

    def showForegroundScalarBar(self):
        qt.QSettings().setValue('DataProbe/sliceViewAnnotations.scalarBarEnabled', 1)
        qt.QSettings().setValue(
            'DataProbe/sliceViewAnnotations.scalarBarSelectedLayer', 'foreground')
        import DataProbeLib
        DataProbeLib.SliceAnnotations().updateSliceViewFromGUI()

    def dataFrameToTable(self, dataFrame, tableNode, indexName='Structure'):
        if tableNode is None:
            tableNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLTableNode')
            tableNode.SetUseColumnNameAsColumnHeader(True)
            tableNode.SetUseFirstColumnAsRowHeader(True)
            tableNode.SetLocked(True)
        tableWasModified = tableNode.StartModify()
        tableNode.RemoveAllColumns()

        indexColumn = tableNode.AddColumn()
        indexColumn.SetName(indexName)

        for columnName in dataFrame.columns:
            column = tableNode.AddColumn()
            column.SetName(columnName)

        for i, (rowName, row) in enumerate(dataFrame.iterrows()):
            tableNode.AddEmptyRow()
            tableNode.SetCellText(i, 0, rowName)
            for j, value in enumerate(row.values, start=1):
                tableNode.SetCellText(i, j, value)

        tableNode.Modified()  # is this necessary?
        tableNode.EndModify(tableWasModified)
        return tableNode

    def exportToTable(self, tableNode, scoresDict):
        if tableNode is None:
            tableNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLTableNode')
        tableWasModified = tableNode.StartModify()
        tableNode.RemoveAllColumns()
        # Sort from large to small and remove zeros
        scoresDict = {
            k: v
            for k, v
            in sorted(scoresDict.items(), key=lambda item: item[1], reverse=True)
            if v > 0
        }
        structuresColumn = tableNode.AddColumn(vtk.vtkStringArray())
        structuresColumn.SetName('Structure')
        scoresColumn = tableNode.AddColumn(vtk.vtkDoubleArray())
        scoresColumn.SetName('Score')

        # Fill columns
        table = tableNode.GetTable()
        for label, score in scoresDict.items():
            rowIndex = tableNode.AddEmptyRow()
            table.GetColumn(0).SetValue(rowIndex, str(label))
            table.GetColumn(1).SetValue(rowIndex, score)
        tableNode.Modified()
        tableNode.EndModify(tableWasModified)
        return tableNode

    def showTableInModuleLayout(self, tableView, tableNode):
        tableView.setMRMLTableNode(tableNode)
        tableView.show()

    def showTableInViewLayout(self, tableNode):
        currentLayout = slicer.app.layoutManager().layout
        tablesLogic = slicer.modules.tables.logic()
        appLogic = slicer.app.applicationLogic()

        layoutWithTable = tablesLogic.GetLayoutWithTable(currentLayout)
        slicer.app.layoutManager().setLayout(layoutWithTable)
        appLogic.GetSelectionNode().SetActiveTableID(tableNode.GetID())
        appLogic.PropagateTableSelection()

    def jumpToMax(self, volumeNode):
        array = slicer.util.array(volumeNode.GetID())
        maxIndices = np.array(np.where(array == array.max())).T
        meanMaxIdx = maxIndices.mean(
            axis=0)[::-1].astype(np.uint16).tolist()  # numpy to sitk
        image = su.PullVolumeFromSlicer(volumeNode)
        point = image.TransformContinuousIndexToPhysicalPoint(meanMaxIdx)
        point = np.array(point)
        point[:2] *= -1  # LPS to RAS
        self.jumpSlices(point)

    def jumpSlices(self, center):
        colors = 'Yellow', 'Green', 'Red'
        for (color, offset) in zip(colors, center):
            sliceLogic = slicer.app.layoutManager().sliceWidget(color).sliceLogic()
            sliceLogic.SetSliceOffset(offset)

    def jump3D(self, center):
        layoutManager = slicer.app.layoutManager()
        threeDWidget = layoutManager.threeDWidget(0)
        threeDView = threeDWidget.threeDView()
        threeDView.setFocalPoint(*center)

    def combineByLobe(self, dataFrame, lobesMapping):
        """This method is not working yet."""
        from collections import defaultdict
        slicer.df = dataFrame
        dataFrame = dataFrame.copy()
        result = dataFrame.copy()

        dataFrame.columns = [str(n) for n in dataFrame.columns]
        resultArray = np.zeros_like(np.array(dataFrame))

        # https://stackoverflow.com/a/42636819/3956024
        for col in result.columns:
            if np.issubdtype(result[col].dtype, np.number):
                result[col].values[:] = 0

        for i, row in enumerate(list(dataFrame.itertuples())):
            totals = defaultdict(int)
            for lobe, labels in lobesMapping.items():
                for label in labels:
                    try:
                        slicer.df = dataFrame
                        totals[lobe] += dataFrame.at[row.Index, str(label)]
                    except KeyError:
                        pass
            for lobe, labels in lobesMapping.items():
                for label in labels:
                    result.at[row.Index, str(label)] = totals[lobe]
        result.columns = [int(n) for n in result.columns]
        slicer.result = result
        return result

    def getStringsDataFrame(
        self,
        semiologiesDataFrame,
        combinedDataFrame,
        removeScoresIfSingle=True,
    ):
        combinedDataFrame = combinedDataFrame.sort_values(
            by='Score', axis=1, ascending=False)
        combinedDataFrame = combinedDataFrame.apply(
            lambda x: [f'{n:.2f}' for n in x])
        semiologiesDataFrame = semiologiesDataFrame.T.reindex(
            combinedDataFrame.T.index).T
        semiologiesDataFrame = semiologiesDataFrame.fillna(0)
        semiologiesDataFrame = semiologiesDataFrame.astype(int)
        semiologiesDataFrame = semiologiesDataFrame.astype(str)
        stringsDataFrame = combinedDataFrame.append(semiologiesDataFrame)
        stringsDataFrame.columns = [
            n.replace('-', ' ') for n in stringsDataFrame.columns]
        if removeScoresIfSingle and len(stringsDataFrame) == 2:
            stringsDataFrame.drop(index='Score', inplace=True)
        return stringsDataFrame

    def getCacheDir(self):
        cacheDir = Path('~/.cache/svt').expanduser()
        cacheDir.mkdir(exist_ok=True, parents=True)
        return cacheDir

    def getCachePath(self):
        path = self.getCacheDir() / 'queries.yml'
        return path

    def readCache(self):
        import yaml
        path = self.getCachePath()
        path.touch()  # in case it doesn't exist yet
        with open(path) as f:
            cache = yaml.full_load(f)
        if cache is None:
            cache = {}
        return cache

    def writeCache(self, cache):
        import yaml
        with open(self.getCachePath(), 'w') as f:
            documents = yaml.dump(cache, f)
        return documents

    def clearCache(self):
        path = self.getCachePath()
        if path.is_file():
            path.unlink()
            slicer.util.delayDisplay(f'Cache removed: {path}')
        else:
            slicer.util.delayDisplay(f'Cache file does not exist yet: {path}')

    def getTextFromDialog(self, parent, title, message):
        dialog = qt.QInputDialog()
        text = dialog.getText(
            parent, 'Add custom semiology term', 'Enter a semiology term:')
        if not text or text.isspace():
            text = None
        return text

    def getCustomSemiologyTermFromDialog(self):
        dialog = CustomSemiologyDialog()
        accept = dialog.exec()
        if not accept:
            term = None
        else:
            return dialog.term

    def dataFrameIsEmpty(self, dataFrame):
        return dataFrame.isna().all().all()


class SemiologyVisualisationTest(ScriptedLoadableModuleTest):
    """
    This is the test case for your scripted module.
    Uses ScriptedLoadableModuleTest base class, available at:
    https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def setUp(self):
        """ Do whatever is needed to reset the state - typically a scene clear will be enough.
        """
        slicer.mrmlScene.Clear(0)

    def runTest(self):
        """Run as few or as many tests as needed here.
        """
        self.setUp()
        self.test_SemiologyVisualisation1()

    def test_SemiologyVisualisation1(self):
        self.delayDisplay("Starting the test")

        widget = slicer.semiologyVisualisation
        self.delayDisplay('Finished with download and loading')
        self.delayDisplay('Test passed!')


class Parcellation(ABC):
    def __init__(self, segmentationPath):
        self.segmentationPath = Path(segmentationPath)
        self.segmentationNode = None
        self._labelMap = None

    # Note that @property must come before @abstractmethod
    @property
    @abstractmethod
    def colorTable(self):
        pass

    @property
    def segmentation(self):
        return self.segmentationNode.GetSegmentation()

    def getSegmentIDs(self):
        stringArray = vtk.vtkStringArray()
        self.segmentation.GetSegmentIDs(stringArray)
        segmentIDs = [
            stringArray.GetValue(n)
            for n in range(stringArray.GetNumberOfValues())
        ]
        return segmentIDs

    def getSegments(self):
        return [self.segmentation.GetSegment(x) for x in self.getSegmentIDs()]

    def load(self):
        stem = self.segmentationPath.name.split('.')[0]
        try:
            node = slicer.util.getNode(stem)
            logging.info(f'Segmentation found in scene: {stem}')
        except slicer.util.MRMLNodeNotFoundException:
            logging.info(f'Segmentation not found in scene: {stem}')
            logging.info(f'Loading from {self.segmentationPath}...')
            node = slicer.util.loadSegmentation(str(self.segmentationPath))
        self.segmentationNode = node
        self.segmentationNode.GetDisplayNode().SetOpacity2DFill(1)

    def isValidNumber(self, number):
        return self.colorTable.isValidNumber(number)

    def getColorFromName(self, name):
        return self.colorTable.getColorFromName(name)

    def getColorFromSegment(self, segment):
        return self.getColorFromName(segment.GetName())

    def getLabelFromName(self, name):
        return self.colorTable.getLabelFromName(name)

    def getLabelFromSegment(self, segment):
        return self.getLabelFromName(segment.GetName())

    def setOriginalColors(self, showProgress=True):
        segments = self.getSegments()
        numSegments = len(segments)
        if showProgress:
            progressDialog = slicer.util.createProgressDialog(
                value=0,
                maximum=numSegments,
                windowTitle='Setting colors...',
            )
        for i, segment in enumerate(segments):
            if showProgress:
                progressDialog.setValue(i)
                progressDialog.setLabelText(segment.GetName())
                slicer.app.processEvents()
            color = self.getColorFromSegment(segment)
            segment.SetColor(color)
            self.setSegmentOpacity(segment, 1, dimension=2)
            self.setSegmentOpacity(segment, 1, dimension=3)
        if showProgress:
            progressDialog.setValue(numSegments)
            slicer.app.processEvents()
            progressDialog.close()

    def setScoresColors(
        self,
        scoresDict: Dict[int, float],
        colorNode,
        defaultColor,
        showLeft=True,
        showRight=True,
        showProgress=True,
        min2dOpacity=1,
    ):
        """[summary]

        Args:
            scoresDict: Dictionary mapping GIF label numbers to scores (datapoints or numbers between 0 and 100)
            colorNode ([type]): [description]
            defaultColor ([type]): [description]
            showLeft (bool, optional): [description]. Defaults to True.
            showRight (bool, optional): [description]. Defaults to True.
            showProgress (bool, optional): [description]. Defaults to True.
            min2dOpacity (int, optional): [description]. Defaults to 1.
        """
        tic = time.time()
        if not showProgress:
            box = qt.QMessageBox()
            box.setStandardButtons(0)
            box.setText('Setting colours...')
            box.show()
            slicer.app.processEvents()

        segments = self.getSegments()
        numSegments = len(segments)
        if showProgress:
            progressDialog = slicer.util.createProgressDialog(
                value=0,
                maximum=numSegments,
                windowTitle='Setting colours...',
            )
        for i, segment in enumerate(segments):
            if showProgress:
                progressDialog.setValue(i)
                progressDialog.setLabelText(segment.GetName())
                slicer.app.processEvents()
            label = self.getLabelFromSegment(segment)
            if scoresDict is not None:
                scores = np.array(list(scoresDict.values()))
                minScore = min(scores)
                maxScore = max(scores)
            color = defaultColor
            opacity2D = 0
            opacity3D = 1
            if scoresDict is not None and label in scoresDict:
                score = scoresDict[label]
                if score > 0:
                    opacity3D = 1
                    if minScore == maxScore:  # All regions with datapoints have same score
                        normalisedScore = 1
                    else:
                        normalisedScore = score - minScore
                        normalisedScore /= (maxScore - minScore)
                    # opacity2D goes from minOpacity2d to 1.0
                    opacity2D = normalisedScore * \
                        (1 - min2dOpacity) + min2dOpacity
                    color = self.getColorFromScore(normalisedScore, colorNode)
            if not showLeft and 'Left' in segment.GetName():
                opacity3D = 0
            if not showRight and 'Right' in segment.GetName():
                opacity3D = 0
            segment.SetColor(color)
            self.setSegmentOpacity(segment, opacity2D, dimension=2)
            self.setSegmentOpacity(segment, opacity3D, dimension=3)
        if showProgress:
            progressDialog.setValue(numSegments)
            slicer.app.processEvents()
            progressDialog.close()
        else:
            box.accept()
        toc = time.time()
        slicer.util.delayDisplay(
            f'Updating colours took {int(toc - tic)} seconds')
        slicer.app.processEvents()

    def getColorFromScore(self, normalisedScore, colorNode):
        """This method is very important"""
        numColors = colorNode.GetNumberOfColors()
        scoreIndex = int(round((numColors - 1) * normalisedScore))
        colorAlpha = 4 * [0]
        colorNode.GetColor(scoreIndex, colorAlpha)
        color = np.array(colorAlpha[:3])
        return color

    def setRandomColors(self):
        """For debugging purposes"""
        segments = self.getSegments()
        numSegments = len(segments)
        progressDialog = slicer.util.createProgressDialog(
            value=0,
            maximum=numSegments,
            windowTitle='Setting colors...',
        )
        for i, segment in enumerate(segments):
            progressDialog.setValue(i)
            slicer.app.processEvents()
            color = self.getRandomColor()
            segment.SetColor(color)
        progressDialog.setValue(numSegments)
        slicer.app.processEvents()
        progressDialog.close()

    def getRandomColor(self, normalised=True):
        return np.random.rand(3)

    def setSegmentOpacity(self, segment, opacity, dimension):
        displayNode = self.segmentationNode.GetDisplayNode()
        if dimension == 2:
            displayNode.SetSegmentOpacity2DFill(segment.GetName(), opacity)
            displayNode.SetSegmentOpacity2DOutline(segment.GetName(), opacity)
        elif dimension == 3:
            displayNode.SetSegmentOpacity3D(segment.GetName(), opacity)

    def getNameFromLabel(self, label):
        return self.colorTable.getStructureNameFromLabelNumber(label)

    def useNamesForDataFramesColumns(self, *dataFrames):
        for df in dataFrames:
            df.columns = [self.getNameFromLabel(n) for n in df.columns]

    def jumpToStructure(self, name):
        segmentID = name
        centerRas = self.segmentationNode.GetSegmentCenter(segmentID)
        logic = SemiologyVisualisationLogic()
        logic.jumpSlices(centerRas)
        logic.jump3D(centerRas)


class GIFParcellation(Parcellation):
    def __init__(self, segmentationPath, colorTablePath):
        Parcellation.__init__(self, segmentationPath)
        self.colorTablePath = colorTablePath
        self._colorTable = GIFColorTable(self.colorTablePath)

    @property
    def colorTable(self):
        return self._colorTable


class ColorTable(ABC):
    def __init__(self, path):
        self.structuresDict = self.readColorTable(path)

    def getStructureNameFromLabelNumber(self, labelNumber):
        return self.structuresDict[labelNumber]['name']

    def isValidNumber(self, number):
        return number in self.structuresDict

    @staticmethod
    def readColorTable(path):
        structuresDict = {}
        with open(path) as f:
            for row in f:
                label, name, *color, _ = row.split()
                label = int(label)
                color = np.array(color, dtype=np.float) / 255
                structuresDict[label] = dict(name=name, color=color)
        return structuresDict

    def getColorFromName(self, name):
        for structureDict in self.structuresDict.values():
            if structureDict['name'] == name:
                color = structureDict['color']
                break
        else:
            raise KeyError(f'Structure {name} not found in color table')
        return color

    def getLabelFromName(self, name):
        for label, structureDict in self.structuresDict.items():
            if structureDict['name'] == name:
                result = label
                break
        else:
            raise KeyError(f'Structure {name} not found in color table')
        return result


class GIFColorTable(ColorTable):
    def getLobesMapping(self):
        from mega_analysis import gif_lobes_from_excel_sheets
        result = {}
        for key, labels in gif_lobes_from_excel_sheets().items():
            lobe = key.split()[1]
            lobe = lobe.lower() if len(lobe) > 2 else lobe
            left_key = f'Left {lobe}'
            right_key = f'Right {lobe}'
            result[left_key] = []
            result[right_key] = []
            for label in labels:
                name = self.getStructureNameFromLabelNumber(label)
                if 'Left' in name:
                    result[left_key].append(label)
                elif 'Right' in name:
                    result[right_key].append(label)

        result['Cerebellum'] = [72, 73, 74]
        return result


class CustomSemiology:
    def __init__(self, term):
        self.term = term
        self.checkBox = qt.QCheckBox(self.term)
        self.checkBox.toggled.connect(self.onCheckBox)
        self.radioButtons = {
            'left': qt.QRadioButton('Left'),
            'right': qt.QRadioButton('Right'),
            'other': qt.QRadioButton('Other'),
        }
        self.buttonGroup = qt.QButtonGroup()
        for button in self.radioButtons.values():
            self.buttonGroup.addButton(button)
            button.hide()

    def onCheckBox(self, checked):
        for button in self.radioButtons.values():
            button.setVisible(checked)

    def isChecked(self):
        return self.checkBox.isChecked()

    def unCheck(self):
        self.checkBox.setChecked(False)

    @property
    def widgets(self):
        return [self.checkBox, *self.radioButtons.values()]

    @property
    def laterality(self):
        from mega_analysis.semiology import Laterality
        lateralitiesDict = {
            'left': Laterality.LEFT,
            'right': Laterality.RIGHT,
            'other': Laterality.NEUTRAL,
        }
        for lateralityName, laterality in lateralitiesDict.items():
            widget = self.radioButtons[lateralityName]
            if widget.isChecked():
                return laterality


class Query:
    def __init__(self, semiologies):
        if isinstance(semiologies, (str, Path)):
            self.semiologies = self.read(semiologies)
        else:
            self.semiologies = semiologies

    def toDicts(self):
        content = []
        for semiology in self.semiologies:
            semiology_dict = dict(
                term=semiology.term,
                symptoms_side=semiology.symptoms_side.value,
                dominant_hemisphere=semiology.dominant_hemisphere,
                granular=semiology.granular,
                include_concordance=semiology.include_concordance,
                include_seeg=semiology.include_seeg,
                include_cortical_stimulation=semiology.include_cortical_stimulation,
                include_et_topology_ez=semiology.include_et_topology_ez,
                include_spontaneous_semiology=semiology.include_spontaneous_semiology,
                include_only_paediatric_cases=semiology.include_only_paediatric_cases,
                include_postictals=semiology.include_postictals,
                inverse_localising_values=semiology.inverse_localising_values,
            )
            content.append(semiology_dict)
        return content

    def hash(self):
        return make_hash_sha256(self.toDicts())

    def write(self, path):
        import yaml
        with open(path, 'w') as f:
            documents = yaml.dump(self.toDicts(), f)
        return documents

    def read(self, path):
        pass


class Scores:
    def __init__(self, scores):
        import pandas as pd
        if isinstance(scores, pd.DataFrame):
            self.df = scores
        elif isinstance(scores, dict):
            self.df = pd.DataFrame.from_records(scores)

    def toDict(self):
        return self.df.to_dict()


@contextmanager
def messageContextManager(message):
    box = qt.QMessageBox()
    box.setStandardButtons(0)
    box.setText(message)
    box.show()
    slicer.app.processEvents()
    yield
    box.accept()


# https://stackoverflow.com/a/42151923/3956024


def make_hash_sha256(o):
    hasher = hashlib.sha256()
    hasher.update(repr(make_hashable(o)).encode())
    return base64.b64encode(hasher.digest()).decode()


def make_hashable(o):
    if isinstance(o, (tuple, list)):
        return tuple((make_hashable(e) for e in o))
    if isinstance(o, dict):
        return tuple(sorted((k, make_hashable(v)) for k, v in o.items()))
    if isinstance(o, (set, frozenset)):
        return tuple(sorted(make_hashable(e) for e in o))
    return o


class CustomSemiologyDialog(qt.QDialog):
    def __init__(self, minimumTermLength=3):
        super().__init__()
        self.minimumTermLength = minimumTermLength
        self.verticalLayout = qt.QVBoxLayout(self)
        self.verticalLayout.setObjectName("verticalLayout")
        self.label = qt.QLabel('Enter a custom semiology term:')
        self.verticalLayout.addWidget(self.label)
        self.lineEdit = qt.QLineEdit()
        self.verticalLayout.addWidget(self.lineEdit)
        # spacerItem = qt.QSpacerItem(20, 40, qt.QSizePolicy.Minimum, qt.QSizePolicy.Expanding)
        # self.verticalLayout.addItem(spacerItem)
        self.label_2 = qt.QLabel()
        self.verticalLayout.addWidget(self.label_2)
        self.buttonBox = qt.QDialogButtonBox()
        self.buttonBox.setOrientation(qt.Qt.Horizontal)
        self.buttonBox.setStandardButtons(
            qt.QDialogButtonBox.Cancel | qt.QDialogButtonBox.Ok)
        self.buttonBox.setObjectName("buttonBox")
        self.verticalLayout.addWidget(self.buttonBox)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.lineEdit.textChanged.connect(self.textChanged)
        self.searchFunction = self.getSearchFunction()

    @property
    def term(self):
        return self.lineEdit.text

    def getSearchFunction(self):
        from mega_analysis import custom_semiology_lookup
        return custom_semiology_lookup

    def textChanged(self):
        if not self.term or len(self.term) < self.minimumTermLength:
            self.label_2.setText('')
            return
        terms = self.searchFunction(self.term)
        if not terms:
            self.label_2.setText('')
            return
        lines = ['This semiology term exists under the following categories:\n']
        for term in terms:
            lines.append(f'- {term}')
        lines.append(
            f'\nIf you wish to only search for "{self.term}", press OK.'
            '\nOtherwise, select the previous categories in the main module interface'
        )
        self.label_2.setText('\n'.join(lines))
