#include "dsp/KeyDetector.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>
#include <vector>

namespace
{
template <typename T>
bool readExact (const char* path, T* output, size_t count)
{
    std::ifstream stream (path, std::ios::binary | std::ios::ate);
    if (! stream || (size_t) stream.tellg() != count * sizeof (T))
        return false;
    stream.seekg (0);
    return (bool) stream.read (reinterpret_cast<char*> (output),
                               (std::streamsize) (count * sizeof (T)));
}

float maxError (const float* actual, const float* expected, size_t count)
{
    float error = 0.0f;
    for (size_t index = 0; index < count; ++index)
        error = std::max (error, std::abs (actual[index] - expected[index]));
    return error;
}
}

int main (int argc, char** argv)
{
    if (argc != 5)
    {
        std::cerr << "usage: TRENCH_KeyModelParity model.json audio.f32 chroma.f32 probabilities.f32\n";
        return 2;
    }

    std::ifstream modelStream (argv[1], std::ios::binary);
    const std::string modelJson ((std::istreambuf_iterator<char> (modelStream)),
                                 std::istreambuf_iterator<char>());
    std::vector<float> audio ((size_t) trench::KeyDetector::kFftSize);
    std::array<float, 12> expectedChroma {};
    std::array<float, 24> expectedProbabilities {};
    if (modelJson.empty()
        || ! readExact (argv[2], audio.data(), audio.size())
        || ! readExact (argv[3], expectedChroma.data(), expectedChroma.size())
        || ! readExact (argv[4], expectedProbabilities.data(), expectedProbabilities.size()))
    {
        std::cerr << "invalid parity input\n";
        return 3;
    }

    trench::KeyDetector detector;
    if (! detector.loadModel (modelJson.data(), modelJson.size()))
    {
        std::cerr << "RTNeural model load failed\n";
        return 4;
    }

    std::array<float, 12> actualChroma {};
    if (! detector.computeChroma (audio.data(), (int) audio.size(), actualChroma))
    {
        std::cerr << "C++ chroma frontend failed\n";
        return 5;
    }
    const float chromaError = maxError (
        actualChroma.data(), expectedChroma.data(), expectedChroma.size());

    trench::KeyDetector::Result result;
    std::array<float, 24> actualProbabilities {};
    if (! detector.inferChroma (actualChroma, result, &actualProbabilities))
    {
        std::cerr << "RTNeural inference failed\n";
        return 6;
    }
    const float probabilityError = maxError (
        actualProbabilities.data(), expectedProbabilities.data(), expectedProbabilities.size());

    std::cout << "frontend max abs error: " << chromaError << '\n'
              << "RTNeural max abs error: " << probabilityError << '\n'
              << "prediction: " << result.labelIndex << " confidence: " << result.confidence << '\n';
    if (chromaError > 5.0e-4f || probabilityError > 5.0e-4f)
        return 7;
    return 0;
}
