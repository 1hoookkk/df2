#include "PluginProcessor.h"
#include "PluginEditor.h"
#include "TrenchChassisLayout.h"
#include "BinaryData.h"

#include <cmath>

//==============================================================================
PluginProcessor::PluginProcessor()
     : AudioProcessor (BusesProperties()
                      #if ! JucePlugin_IsMidiEffect
                       #if ! JucePlugin_IsSynth
                        .withInput  ("Input",  juce::AudioChannelSet::stereo(), true)
                       #endif
                        .withOutput ("Output", juce::AudioChannelSet::stereo(), true)
                      #endif
                        ),
       apvts (*this, nullptr, "TRENCH_STATE", TrenchParameters::createParameterLayout()),
       authoringSlot (dspBridge)
{
    // Default shipping body/cartridge. sonic_tables.json currently identifies P2k_013 at 39062.5 Hz.
    dspBridge.loadCartridge (juce::String::createStringFromData (BinaryData::sonic_tables_json,
                                                                 BinaryData::sonic_tables_jsonSize));

    // Seed Documents/TRENCH/ + chassis_variants/ so the user has a known
    // place to drop variants and a runtime_layout.json to edit "active" in.
    // Done in the processor (not editor) so the editor stays simple.
    trench::layout::ensureDevDirs();
}

PluginProcessor::~PluginProcessor() = default;

//==============================================================================
const juce::String PluginProcessor::getName() const { return JucePlugin_Name; }

bool PluginProcessor::acceptsMidi() const
{
   #if JucePlugin_WantsMidiInput
    return true;
   #else
    return false;
   #endif
}

bool PluginProcessor::producesMidi() const
{
   #if JucePlugin_ProducesMidiOutput
    return true;
   #else
    return false;
   #endif
}

bool PluginProcessor::isMidiEffect() const
{
   #if JucePlugin_IsMidiEffect
    return true;
   #else
    return false;
   #endif
}

double PluginProcessor::getTailLengthSeconds() const { return 0.0; }

int PluginProcessor::getNumPrograms() { return 1; }
int PluginProcessor::getCurrentProgram() { return 0; }
void PluginProcessor::setCurrentProgram (int index) { juce::ignoreUnused (index); }
const juce::String PluginProcessor::getProgramName (int index)
{
    juce::ignoreUnused (index);
    return "SPEAKER KNOCKERZ";
}
void PluginProcessor::changeProgramName (int index, const juce::String& newName)
{
    juce::ignoreUnused (index, newName);
}

//==============================================================================
void PluginProcessor::prepareToPlay (double sampleRate, int samplesPerBlock)
{
    fixedRateIsland.prepare (sampleRate, samplesPerBlock, dspBridge);
    setLatencySamples (fixedRateIsland.getLatencySamples());
}

void PluginProcessor::releaseResources()
{
    dspBridge.reset();
}

bool PluginProcessor::isBusesLayoutSupported (const BusesLayout& layouts) const
{
  #if JucePlugin_IsMidiEffect
    juce::ignoreUnused (layouts);
    return true;
  #else
    if (layouts.getMainOutputChannelSet() != juce::AudioChannelSet::mono()
     && layouts.getMainOutputChannelSet() != juce::AudioChannelSet::stereo())
        return false;

   #if ! JucePlugin_IsSynth
    if (layouts.getMainOutputChannelSet() != layouts.getMainInputChannelSet())
        return false;
   #endif

    return true;
  #endif
}

void PluginProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midiMessages)
{
    juce::ignoreUnused (midiMessages);
    juce::ScopedNoDenormals noDenormals;

    for (auto ch = getTotalNumInputChannels(); ch < getTotalNumOutputChannels(); ++ch)
        buffer.clear (ch, 0, buffer.getNumSamples());

    TrenchParams params;
    params.morph = apvts.getRawParameterValue (ParamID::morph)->load();
    params.q     = apvts.getRawParameterValue (ParamID::q)->load();
    params.slamDrive = apvts.getRawParameterValue (ParamID::slamDrive)->load();
    // fiveD retired from the user-facing UI but the engine still consumes the
    // 4th param. Pass 0.75f — the previous APVTS default — so the audio path
    // matches the last-known-good DSP behaviour exactly.
    params.fiveD = 0.75f;

    // Only fire trench_engine_set_input_mode when the parameter ACTUALLY
    // changes. Calling it every block thrashes the engine's input-character
    // stage and was the source of the post-UI-pass audio regression.
    if (auto* mp = apvts.getRawParameterValue (ParamID::inputMode))
    {
        const int currentMode = static_cast<int> (mp->load (std::memory_order_relaxed));
        if (currentMode != lastInputModeSent)
        {
            dspBridge.setInputMode (currentMode);
            lastInputModeSent = currentMode;
        }
    }

    auto channelPeak = [&buffer] (int channel)
    {
        if (channel >= buffer.getNumChannels() || buffer.getNumSamples() <= 0)
            return 0.0f;

        const auto* data = buffer.getReadPointer (channel);
        float peak = 0.0f;
        for (int i = 0; i < buffer.getNumSamples(); ++i)
            peak = juce::jmax (peak, std::abs (data[i]));

        return juce::jlimit (0.0f, 1.0f, peak);
    };

    auto smoothMeter = [] (std::atomic<float>& target, float next)
    {
        const float prev = target.load (std::memory_order_relaxed);
        const float smoothed = next > prev ? next : prev * 0.86f + next * 0.14f;
        target.store (smoothed, std::memory_order_relaxed);
    };

    smoothMeter (inputMeterL, channelPeak (0));
    smoothMeter (inputMeterR, channelPeak (1));

    fixedRateIsland.process (buffer, dspBridge, params);

    // Feed the UI vectorscope with the post-filter stereo signal.
    if (buffer.getNumSamples() > 0)
    {
        const auto* postL = buffer.getReadPointer (0);
        const auto* postR = buffer.getNumChannels() > 1 ? buffer.getReadPointer (1) : postL;
        int wp = scopeWritePos.load (std::memory_order_relaxed);
        for (int i = 0; i < buffer.getNumSamples(); ++i)
        {
            scopeL[(size_t) wp].store (postL[i], std::memory_order_relaxed);
            scopeR[(size_t) wp].store (postR[i], std::memory_order_relaxed);
            wp = (wp + 1) & (kScopeLen - 1);
        }
        scopeWritePos.store (wp, std::memory_order_relaxed);
    }
}

int PluginProcessor::copyScopeSamples (float* outL, float* outR, int count) const noexcept
{
    if (outL == nullptr || outR == nullptr || count <= 0)
        return 0;

    count = juce::jmin (count, kScopeLen);
    const int wp = scopeWritePos.load (std::memory_order_relaxed);
    // Walk back `count` samples from the write head, emitting oldest -> newest.
    for (int i = 0; i < count; ++i)
    {
        const int idx = (wp - count + i) & (kScopeLen - 1);
        outL[i] = scopeL[(size_t) idx].load (std::memory_order_relaxed);
        outR[i] = scopeR[(size_t) idx].load (std::memory_order_relaxed);
    }
    return count;
}

//==============================================================================
bool PluginProcessor::hasEditor() const { return true; }

juce::AudioProcessorEditor* PluginProcessor::createEditor()
{
    return new PluginEditor (*this);
}

//==============================================================================
void PluginProcessor::getStateInformation (juce::MemoryBlock& destData)
{
    auto state = apvts.copyState();
    std::unique_ptr<juce::XmlElement> xml (state.createXml());
    copyXmlToBinary (*xml, destData);
}

void PluginProcessor::setStateInformation (const void* data, int sizeInBytes)
{
    std::unique_ptr<juce::XmlElement> xmlState (getXmlFromBinary (data, sizeInBytes));
    if (xmlState != nullptr && xmlState->hasTagName (apvts.state.getType()))
        apvts.replaceState (juce::ValueTree::fromXml (*xmlState));
}

//==============================================================================
juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new PluginProcessor();
}
