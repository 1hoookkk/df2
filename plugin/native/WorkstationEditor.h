#pragma once

#include "PluginProcessor.h"
#include <juce_gui_basics/juce_gui_basics.h>
#include <juce_audio_processors/juce_audio_processors.h>
#include <array>
#include <vector>

// audition loop control, provided by the standalone app's audio layer
struct WorkstationLoop
{
    virtual ~WorkstationLoop() = default;
    virtual bool loadFile (const juce::File& f) = 0;
    virtual void setPlaying (bool shouldPlay) = 0;
    virtual bool isPlaying() const = 0;
    virtual juce::String loopName() const = 0;
};
extern WorkstationLoop* gWorkstationLoop;

class WorkstationEditor final : public juce::Component,
                                public juce::FileDragAndDropTarget,
                                private juce::Timer
{
public:
    explicit WorkstationEditor (PluginProcessor& processor);
    ~WorkstationEditor() override;

    void paint (juce::Graphics& g) override;
    void resized() override;
    void mouseDown (const juce::MouseEvent& e) override;
    void mouseDrag (const juce::MouseEvent& e) override;
    void mouseUp (const juce::MouseEvent& e) override;
    void mouseDoubleClick (const juce::MouseEvent& e) override;
    void mouseWheelMove (const juce::MouseEvent& e, const juce::MouseWheelDetails& wheel) override;
    bool keyPressed (const juce::KeyPress& key) override;
    bool isInterestedInFileDrag (const juce::StringArray& files) override;
    void filesDropped (const juce::StringArray& files, int x, int y) override;

    // Dense enough that narrow packed-runtime notches and peaks are not softened
    // by the display sampling itself.
    static constexpr int kNumPlotPoints = 1024;
private:
    // ------------------------------------------------------------- node index
    // BIN: user/lab programs, P2K source poses/stages, and measured authoring
    // rails. No generated pool scan and no comparison/reference workflow.
    enum class NodeKind { UserBody, LabBody, P2k, MeasuredRail, X3Ref };
    struct Node
    {
        NodeKind kind = NodeKind::UserBody;
        juce::String stem;
        juce::File body;          // .body240 (UserBody) or compiled-v1 .json (P2k)
        bool loadable = false;
        int refIndex = -1;        // X3 reference curve set
        juce::String note;        // provenance / role shown on selection
    };
    struct Section
    {
        NodeKind kind;
        juce::String title;
        std::vector<int> nodes;   // indices into nodes[]
        bool open = true;
    };
    struct Row
    {
        bool isSection = false;
        int section = -1;
        int node = -1;            // index into nodes[] when ! isSection
    };
    struct RefItem
    {
        juce::String name;
        juce::File file;
    };

    void timerCallback() override;

    // data plumbing
    void scanBin();
    void rebuildRows();
    void writeIndexJson() const;
    bool nodeBytes (const Node& node, std::array<juce::uint8, 240>& out) const;
    void loadProgram (int nodeIndex);
    void loadSource (int nodeIndex);
    bool packAndInstall (bool certify = true);   // certify=false: light drag-time install
    void toggleLaneOff (int lane);
    void insertSourceLane();
    void insertSourceLaneAtCorner();   // donor stage into the active corner only

    // measured rails as stage donors: parsed pole/zero pairs, encoder-snapped
    struct RailPair { double poleHz, poleR, zeroHz, zeroR; };
    struct RailEntry { juce::String name; std::vector<RailPair> pairs;
                       std::vector<double> bMeas, aMeas; };   // the entry's own fitted response
    bool railActive = false;
    juce::String railSourceName;
    std::vector<RailEntry> railEntries;
    int railIndex = 0;
    juce::uint16 railChipWords[6][5] {};
    bool railChipValid[6] {};
    void loadRail (const juce::File& file, const juce::String& name);
    void selectRailEntry (int index);
    void insertRailStage (int chip, int lane, bool cornerOnly);
    void applyRailPose (int corner);       // whole entry -> 6-stage pose at one corner
    juce::uint16 railPoseWords[6][5] {};   // the fitted pose (identity-padded)
    double railPoseResidualDb = -1.0;      // RMS vs the measured response, 200 Hz - 16 kHz
    juce::Rectangle<int> railPoseChipArea() const;
    // canonical fit: shells out to df2/tools/rail_fit_pose.py (forge_fit)
    juce::ChildProcess railFitProcess;
    juce::File railFile, railFitOut;
    bool railFitting = false;
    juce::Rectangle<int> railFitArea() const;
    void startRailFit();
    void finishRailFit();
    juce::Rectangle<int> railPrevArea() const;
    juce::Rectangle<int> railNextArea() const;
    void moveLane (int from, int to);
    void copyPoseToCorner (int donorCorner, int corner);   // whole 6-stage pose from the bank
    // Dormant project-derived experiment; not exposed as E-mu Morph Designer UI.
    void useSourceAsQLaw();
    void applyMeasuredQLaw();   // MD-Q: the measured ROM Q transform, no donor needed
    bool regenerateQLawEdge();
    void saveWorkingBody();
    void loadReference (int refIndex);
    void refreshCurves();
    bool laneIsIdentity (const juce::uint16 (&words)[4][6][5], int lane) const;

    // numeric PROPERTIES editing: roots edited, minifloat-snapped through the
    // real encoder (words are the truth; the display re-derives from the words)
    juce::Rectangle<int> propValueArea (int field) const;   // 0 poleHz 1 poleR 2 zeroHz 3 zeroR 4 scale
    void beginPropEdit (int field);
    void commitPropEdit();
    void setStageRoot (int field, double value);
    void setPoleZero (bool zero, double hz, double r, bool light = false);

    // native pole-zero WINDOW (opened from PROPERTIES; points from the runtime probe)
    bool pzWindowOpen = false;
    juce::Rectangle<int> pzWindowArea() const;
    juce::Rectangle<int> pzCloseArea() const;
    juce::Rectangle<int> pzOpenButtonArea() const;
    juce::Point<float> pzPointFor (double hz, double r) const;
    void drawPzWindow (juce::Graphics& g);
    // runtime pole/zero of one probed stage (roots of the interpolated biquad)
    static bool biquadRoots (const float* c, bool zero, double& hz, double& r);

    // quick undo (snapshot stack, ctrl+Z or button) + reset to the loaded body
    void pushUndo();
    void undo();
    void redo();
    void resetProgram();

    // parameters (normalized 0..1)
    float paramValue (const char* paramID) const;
    void setParamValue (const char* paramID, float normalized);
    void jumpToPose (int corner);   // the corner IS the pose: morph/q follow it

    // layout (single source of truth for paint + hit tests)
    juce::Rectangle<int> headerArea() const;
    juce::Rectangle<int> footerArea() const;
    juce::Rectangle<int> binArea() const;
    juce::Rectangle<int> binSearchArea() const;
    juce::Rectangle<int> binListArea() const;
    juce::Rectangle<int> propertiesArea() const;
    juce::Rectangle<int> centreArea() const;
    juce::Rectangle<int> lanesArea() const;
    juce::Rectangle<int> trayArea() const;       // donor tray (empty when no source)
    juce::Rectangle<int> heroArea() const;       // the working body's overall cascade
    juce::Rectangle<int> gridArea() const;       // the 2x2 corner grid / XY pad
    juce::Rectangle<int> gridCellArea (int corner) const;
    juce::Rectangle<int> binRowArea (int visibleRow) const;
    juce::Rectangle<int> laneRowArea (int lane) const;
    juce::Rectangle<int> laneMiniArea (int lane) const;      // START (M0) endpoint mini
    juce::Rectangle<int> laneMiniEndArea (int lane) const;   // END (M100) endpoint mini
    juce::Rectangle<int> trayPoseChipArea (int corner) const;
    juce::Rectangle<int> trayChipArea (int lane) const;
    juce::Rectangle<int> trayCloseArea() const;
    juce::Rectangle<int> qLawButtonArea() const;
    juce::Rectangle<int> mdqButtonArea() const;
    juce::Rectangle<int> nameBoxArea() const;
    juce::Rectangle<int> saveButtonArea() const;
    juce::Rectangle<int> undoButtonArea() const;
    juce::Rectangle<int> resetButtonArea() const;
    juce::Rectangle<int> redoButtonArea() const;
    juce::Rectangle<int> playButtonArea() const;
    juce::Rectangle<int> chainButtonArea() const;

    // painting
    void drawHeader (juce::Graphics& g);
    void drawBin (juce::Graphics& g);
    void drawHero (juce::Graphics& g);
    void drawGrid (juce::Graphics& g);
    void drawTray (juce::Graphics& g);
    void drawLanes (juce::Graphics& g);
    void drawProperties (juce::Graphics& g);
    void drawFooter (juce::Graphics& g);
    void drawDragGhost (juce::Graphics& g);
    void drawFlatButton (juce::Graphics& g, juce::Rectangle<int> r, const juce::String& label,
                         bool active, bool enabled) const;
    // the miniplot language: single curve, 0 dB line, thin border, nothing else
    void drawMiniPlot (juce::Graphics& g, juce::Rectangle<float> r, const float* db, int n,
                       juce::Colour curve, juce::Colour outline, float outlineThickness) const;

    float xForFrequency (double hz, float plotLeft, float plotWidth) const;
    float yForDb (float db, float plotTop, float plotHeight) const;

    PluginProcessor& processor;

    // indexed BIN navigator + body name entry
    juce::TextEditor binSearch;
    juce::TextEditor nameField;

    // inline numeric editor for a PROPERTIES value
    juce::TextEditor propEditor;
    int editingProp = -1;        // 0..4 while editing, else -1

    // drag-and-drop state (custom paint, no stock widgets)
    enum class DragKind { None, Chip, PoseChip, Lane, PZ, XY, HeroPole, RailChip };
    DragKind dragKind = DragKind::None;
    int dragIndex = -1;          // chip: donor lane; posechip: donor corner; lane: program lane
    bool dragActive = false;     // passed the movement threshold
    bool pzDragZero = false;
    int pzLock = 0;              // 0 free, 1 poles only (zeros locked), 2 zeros only (poles locked)
    juce::Rectangle<int> pzLockArea() const;
    double heroDragStartR = 0.0;   // authored pole r at hero-drag start
    int heroDragStartY = 0;
    bool heroBoth = false;         // puck mid-morph: drag shifts BOTH endpoints
    double heroGrabHz = 0.0;
    double heroOrigRoots[2][5] {}; // start/end authored roots at drag start     // PZ drag: true = zero handle, false = pole handle
    juce::Point<int> dragPos;
    int dropTargetLane = -1;
    int dropTargetCorner = -1;   // endpoint chip over a grid cell

    // PROGRAM: the working body (words are the truth; bytes regenerated on edit)
    bool hasBody = false;
    bool dirty = false;
    juce::String bodyName;
    juce::uint16 words[4][6][5] {};
    std::array<juce::uint8, 240> workingBytes {};
    std::array<juce::uint8, 240> loadedBytes {};   // as loaded: the RESET target
    std::vector<std::array<juce::uint16, 120>> undoStack;
    std::vector<std::array<juce::uint16, 120>> redoStack;

    // SOURCE: read-only donor (feeds the tray chips)
    bool hasSource = false;
    juce::String sourceName;
    juce::uint16 sourceWords[4][6][5] {};
    std::array<juce::uint8, 240> sourceBytes {};
    bool hasQLaw = false;
    juce::String qLawName;
    juce::uint16 qLawWords[4][6][5] {};

    // identity row for OFF lanes + mute restore backups
    juce::uint16 identityWords[5] {};
    juce::uint16 muteBackup[6][4][5] {};
    bool muteBackupValid[6] {};

    // index
    std::vector<Node> nodes;
    std::vector<Section> sections;
    std::vector<Row> rows;
    std::vector<RefItem> refItems;
    int binScroll = 0;
    juce::String binQuery;
    int selectedNode = -1;
    int activeRef = -1;
    juce::String refName;
    std::vector<float> refFreqs;
    std::array<std::vector<float>, 4> refCornerDb;

    // selection
    int activeCorner = 0;
    int selectedLane = 0;
    int sourceLane = 0;

    // probed curves (packed runtime)
    bool programProbeOk = false;
    bool sourceProbeOk = false;
    float programCoeffs[30] {};        // runtime-probed biquads at the current pose
    juce::uint32 programUnstableMask = 0, programNonfiniteMask = 0;   // per-stage probe flags
    std::array<std::array<float, kNumPlotPoints>, 6> programLaneDb {};
    std::array<float, kNumPlotPoints> programSumDb {};
    std::array<std::array<float, kNumPlotPoints>, 6> sourceLaneDb {};
    std::array<float, kNumPlotPoints> sourceSumDb {};
    std::array<std::array<float, kNumPlotPoints>, 4> cornerSumDb {};
    std::array<std::array<std::array<float, kNumPlotPoints>, 6>, 4> cornerLaneDb {};   // per-stage per-corner
    bool cornerProbeOk[4] {};
    std::array<std::array<float, kNumPlotPoints>, 4> sourcePoseDb {};   // donor pose chips
    bool sourcePoseOk[4] {};
    float lastProbedMorph = -1.0f;
    float lastProbedQ = -1.0f;
    bool curvesStale = true;

    // status
    juce::String statusLine { "load a body from the BIN" };
    double lastCertifyMaxR = 0.0;
    bool lastCertifyPass = false;

    // THE TRENCH DESIGNER: parameter-space authoring over the firmware word
    // recipe (trench-core designer.rs). Sections are the truth while the panel
    // is open; every edit recompiles -> certify -> install (the gate net).
    struct DesignerRowState
    {
        int freq = 64, gain = 64;                              // types 1..3
        double poleHz = 500.0, poleR = 0.95;                   // TYPE FREE
        double zeroHz = 1000.0, zeroR = 0.5, scale = 1.0;
    };
    struct DesignerSectionState
    {
        int type = 0;                                          // 0 off, 1 EQ, 2 LP, 3 HP, 4 FREE
        DesignerRowState lo, hi;
    };
    bool designerOpen = false;
    int designerPage = 0;                                      // 0 = Q0 pose page, 1 = Q100 pose page
    DesignerSectionState dsections[2][6];
    int designerShift = 0;                                     // heritage global shift (-32..31)
    double designerLadderHz[128] {};                           // firmware freq-code ladder, decoded pole Hz
    std::array<std::array<float, kNumPlotPoints>, 5> designerJourneyDb {};
    float designerJourneyCrown[5] {};
    bool designerJourneyOk = false;
    int designerFamily = 0;                                    // 0 RIDE (no-collapse), 1 ARCH (mid crest)
    bool designerJourneyPass = false;
    void designerFrameL10();                                   // active-row crowns +2/+8/+25/+27
    void designerSaveBody();                                   // frame -> re-certify -> candidates
    bool designerJourneyGate() const;
    juce::Rectangle<int> designerFamilyArea() const;
    juce::Rectangle<int> designerSaveArea() const;
    juce::String designerTemplateName;
    juce::TextEditor designerEditor;                           // inline cell editor
    int dsEditStage = -1, dsEditRow = 0, dsEditField = -1;     // active inline edit target

    void toggleDesigner();
    void designerApply();                                      // sections -> body -> certify -> install
    void designerRefreshJourney();
    void designerSetTemplate (int index);
    void designerApplyMotif (int stage, int motif);            // census zero motifs (FREE)
    void designerSketchQ100();                                 // MD-Q bw x0.375 sketch -> FREE sections
    int designerCodeForHz (double hz) const;                   // nearest firmware ladder code
    double designerFieldValue (int stage, int row, int field) const;
    void designerSetField (int stage, int row, int field, double value);
    void designerBeginEdit (int stage, int row, int field);
    void designerCommitEdit();
    void designerShowShapeMenu (int stage);
    void designerShowMotifMenu (int stage);
    void designerShowTemplateMenu();
    juce::Rectangle<int> designerButtonArea() const;           // header toggle
    juce::Rectangle<int> designerArea() const;                 // the panel overlay
    juce::Rectangle<int> designerJourneyArea() const;
    juce::Rectangle<int> designerStageRowArea (int stage) const;
    juce::Rectangle<int> designerShapeArea (int stage) const;
    juce::Rectangle<int> designerMotifArea (int stage) const;
    juce::Rectangle<int> designerCellArea (int stage, int row, int field) const;
    juce::Rectangle<int> designerPageArea (int page) const;
    juce::Rectangle<int> designerTemplateArea() const;
    juce::Rectangle<int> designerSketchArea() const;
    juce::Rectangle<int> designerShiftArea() const;
    juce::Rectangle<int> designerCloseArea() const;
    void drawDesigner (juce::Graphics& g);
    bool designerMouseDown (juce::Point<int> pos);

    // proof harness: TRENCH_WS_SCRIPT env var -> JSON action list, run once after startup
    void runProofScript();
    int findNodeByStem (const juce::String& stem) const;
    juce::var proofActions;
    int proofDelayTicks = 0;
    bool proofPending = false;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (WorkstationEditor)
};
