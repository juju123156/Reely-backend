package com.reely.serviceImpl;

import java.util.ArrayList;
import java.util.Base64;
import java.util.List;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestTemplate;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.reely.common.util.CommonUtil;
import com.reely.dto.MovieDto;
import com.reely.dto.SpotifyDto;
import com.reely.dto.SpotifyDto.SpotifyAlbumTracksDto;
import com.reely.mapper.MovieMapper;
import com.reely.service.KmdbMovieFeignClient;
import com.reely.service.KobisMovieFeignClient;
import com.reely.service.SpotifyFeignClient;
import com.reely.service.TmdbMovieFeignClient;
import com.reely.service.MovieService;

@Service
public class MovieServiceImpl implements MovieService {
    
    private final KobisMovieFeignClient kobisFeignClient;
    private final KmdbMovieFeignClient kmdbFeignClient;
    private final TmdbMovieFeignClient tmdbMovieClient;
    private final SpotifyFeignClient spotifyClient;
    // tmdb 이미지 url
    private static final String imageBaseUrl = "https://image.tmdb.org/t/p/original";

    private final MovieMapper movieMapper;

    String kobisKey = "9eaf43c6cd0bde9c0862c1c2c1e4b434"; 
    String kmdbKey = "MZ53N9719N5IH6Z7G2R9";
    String tmdbKey = "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiI5MWJlODU2OGFhYzg4OGMyMzYxOTliMjBmNTBiZWFhNiIsIm5iZiI6MTc0NDYxNzA1Ni43NjQsInN1YiI6IjY3ZmNiZTYwZWMyMmJhM2I0OWQ5ODg0YyIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.SH_t-hN5ptu6cBiLvpK0DSU0U56ZKWwaXUIchYFkMQM";
    String spotifyClientId = "5b2c9e587cf74849aa331f4c8cf79a9f";
    String spotifyClientSecret = "4ccb21a2472048c69fe4741655125741";

    @Autowired
    public MovieServiceImpl(MovieMapper movieMapper, KobisMovieFeignClient kobisFeignClient, KmdbMovieFeignClient kmdbFeignClient, TmdbMovieFeignClient tmdbFeignClient, SpotifyFeignClient spotifyClient) {
        this.movieMapper = movieMapper;
        this.kobisFeignClient = kobisFeignClient;
        this.kmdbFeignClient = kmdbFeignClient;
        this.tmdbMovieClient = tmdbFeignClient;
        this.spotifyClient = spotifyClient;
    }

    String localFilePath = System.getProperty("user.dir"); // 현재 작업 디렉토리
    String filePath = "/volumes"; // 프로젝트 내부 경로

    @Override
    public SpotifyDto getMovieOst(String movieNm) {
        try {
            // Spotify 액세스 토큰 가져오기
            String accessToken = getSpotifyAccessToken();
            
            // 영화 OST 검색
            String query = movieNm + " soundtrack";
            String jsonResponse = spotifyClient.searchTracks(
                "Bearer " + accessToken,
                query,
                "track",
                10
            );
            
            ObjectMapper objectMapper = new ObjectMapper();
            SpotifyDto spotifyDto = objectMapper.readValue(jsonResponse, SpotifyDto.class);
            return spotifyDto;
        } catch (Exception e) {
            e.printStackTrace();
            return null;
        }
    }

    @Override
    public SpotifyAlbumTracksDto getSpotifyAlbumTracks(String albumId, int limit) {
        try {
            String accessToken = getSpotifyAccessToken();
            String jsonResponse = spotifyClient.getAlbumTracks(
                "Bearer " + accessToken,
                albumId,
                limit
            );
            ObjectMapper objectMapper = new ObjectMapper();
            SpotifyAlbumTracksDto spotifyDto = objectMapper.readValue(jsonResponse, SpotifyAlbumTracksDto.class);
            return spotifyDto;
        } catch (Exception e) {
            e.printStackTrace();
            return null;
        }
    }

    private String getSpotifyAccessToken() throws Exception {
        String credentials = spotifyClientId + ":" + spotifyClientSecret;
        String encodedCredentials = Base64.getEncoder().encodeToString(credentials.getBytes());
        
        HttpHeaders headers = new HttpHeaders();
        headers.set("Authorization", "Basic " + encodedCredentials);
        headers.setContentType(MediaType.APPLICATION_FORM_URLENCODED);
        
        String body = "grant_type=client_credentials";
        
        HttpEntity<String> request = new HttpEntity<>(body, headers);
        
        RestTemplate restTemplate = new RestTemplate();
        ResponseEntity<String> response = restTemplate.postForEntity(
            "https://accounts.spotify.com/api/token",
            request,
            String.class
        );
        
        ObjectMapper objectMapper = new ObjectMapper();
        JsonNode root = objectMapper.readTree(response.getBody());
        return root.get("access_token").asText();
    }

    @Override
    public MovieDto getMovieInfo(int movieId) {
        return movieMapper.getMovieInfo(movieId);
    }

    @Override
    public void insertCrewsInfo(int movieId, JsonNode crewNode) {
        
        List<MovieDto> movieDtoList = new ArrayList<>();
        List<MovieDto> crewImgList = new ArrayList<>();
        ObjectMapper objectMapper = new ObjectMapper();
        try {
            // TMDB API를 통해 감독 정보 조회
            //String tmJsonCredits = tmdbMovieClient.getMovieCredits(String.valueOf(movieDto.getTmdbMovieId()), "Bearer " + tmdbKey, "en-US");
            //ObjectMapper objectMapper = new ObjectMapper();
            //JsonNode creditsNode = objectMapper.readTree(tmJsonCredits);
           // JsonNode crewNode = creditsNode.get("crew");
            
            if (crewNode != null && crewNode.isArray()) {
                for (JsonNode crew : crewNode) {
                    String crewId = crew.get("id").asText();
                    String crewName = crew.get("name").asText();
                    String job = crew.get("job").asText();
                    String department = crew.get("department").asText();
                    
                    // TMDB crew 상세 정보 조회
                    String crewDetail = tmdbMovieClient.getPersonDetails(crewId, "Bearer " + tmdbKey, "en-US", "movie_credits,images");
                    JsonNode crewNodeDetail = objectMapper.readTree(crewDetail);
                    
                    MovieDto crewDto = new MovieDto();

                    // 스태프 정보 저장
                    crewDto.setCrewEnNm(crewName);
                    crewDto.setCrewRole(job);
                    crewDto.setCrewDepartment(department);
                    crewDto.setMovieId(movieId);
                    int newCrewId = movieMapper.getCrewId();
                    crewDto.setCrewId(newCrewId);
                    crewDto.setCrewRole(job);
                    crewDto.setCrewEnNm(crewNodeDetail.get("name").asText());
                    
                    // 생년월일, 사망일 정보 추가
                    String birth = crewNodeDetail.path("birthday").asText(null);
                    crewDto.setCrewBirth(birth);
                    
                    String death = crewNodeDetail.path("deathday").asText(null);
                    crewDto.setCrewDeath(death);

                    // 성별 정보 추가
                    if (crewNodeDetail.has("gender")) {
                        int gender = crewNodeDetail.get("gender").asInt();
                        String genderStr;
                        switch (gender) {
                            case 1:
                                genderStr = "F";
                                break;
                            case 2:
                                genderStr = "M";
                                break;
                            case 3:
                                genderStr = "N";
                                break;
                            default:
                                genderStr = "U"; // Unknown
                        }
                        crewDto.setGender(genderStr);
                    }
    
                    // Director인 경우 추가 정보 설정
                    if ("Director".equals(job)) {
                        crewDto.setDirectorYn("Y");
                        crewDto.setBiography(crewNodeDetail.has("biography") ? crewNodeDetail.get("biography").asText() : null);
                        
                        // KMDB API를 통해 감독 정보 조회
                        String kmdbDirectorInfo = kmdbFeignClient.getMovieInfo(kmdbKey, crewNodeDetail.get("name").asText());
                        JsonNode kmdbNode = objectMapper.readTree(kmdbDirectorInfo);
    
                        // KMDB 정보 설정 (KMDB 정보가 있으면 우선 적용)
                        if (kmdbNode.has("Data") && kmdbNode.get("Data").isArray()) {
                            JsonNode dataArray = kmdbNode.get("Data");
                            if (dataArray.size() > 0) {
                                JsonNode firstData = dataArray.get(0);
                                if (firstData.has("Result") && firstData.get("Result").isArray()) {
                                    JsonNode resultArray = firstData.get("Result");
                                    for (JsonNode result : resultArray) {
                                        if (result.has("directors") && result.get("directors").has("director")) {
                                            JsonNode directors = result.get("directors").get("director");
                                            if (directors.isArray() && directors.size() > 0) {
                                                JsonNode director = directors.get(0);
                                                crewDto.setCrewKoNm(director.get("directorNm").asText());
                                                
                                                // 필모그래피 정보 수집
                                                StringBuilder filmography = new StringBuilder();
                                                if (result.has("title") && result.has("prodYear")) {
                                                    String title = result.get("title").asText()
                                                        .replaceAll(" !HS ", "")
                                                        .replaceAll(" !HE ", "")
                                                        .replaceAll("^\\s+|\\s+$", "")
                                                        .replaceAll(" +", " ")
                                                        .replaceAll("(\\D)\\s+(\\d)", "$1$2");
                                                    String year = result.get("prodYear").asText();
                                                    filmography.append(title)
                                                            .append(" (" + year + ")")
                                                            .append(", ");
                                                }
                                                crewDto.setFilmography(filmography.toString().replaceAll(", $", ""));
                                            }
                                        }
                                    }
                                }
                            }
                        } else {
                            // KMDB 정보가 없는 경우 TMDB 필모그래피 정보 사용
                            StringBuilder filmography = new StringBuilder();
                            if (crewNode.has("movie_credits") && crewNode.get("movie_credits").has("crew")) {
                                JsonNode crewCredits = crewNode.get("movie_credits").get("crew");
                                for (JsonNode credit : crewCredits) {
                                    if ("Director".equals(credit.get("job").asText())) {
                                        String movieTitle = credit.get("title").asText();
                                        String releaseDate = credit.has("release_date") && !credit.get("release_date").isNull() 
                                            ? credit.get("release_date").asText() 
                                            : "";
                                        filmography.append(movieTitle)
                                                  .append(releaseDate.isEmpty() ? "" : " (" + releaseDate.substring(0, 4) + ")")
                                                  .append(", ");
                                    }
                                }
                            }
                            crewDto.setFilmography(filmography.toString().replaceAll(", $", ""));
                        }
                    }
    
                    // 프로필 이미지 처리
                    if (crew.has("profile_path") && !crew.get("profile_path").isNull()) {
                        String profilePath = crew.get("profile_path").asText();
                        String profileUrl = imageBaseUrl + profilePath;
                        String fileExtension = CommonUtil.getExtension(profileUrl);
                        String fileName = CommonUtil.generateFileName(fileExtension);
                        String fPath = localFilePath + filePath + "/crew_profile";
                        CommonUtil.fileDownloader(profileUrl, fPath, fileName);
    
                        crewDto.setFilePath(fPath + "/" + fileName);
                        crewDto.setFileTypCd("006");
                        int fileId = movieMapper.getFileId();
                        crewDto.setFileId(fileId);
                        crewImgList.add(crewDto);
                    }
    
                    movieDtoList.add(crewDto);
                }
            }
    
            if (!movieDtoList.isEmpty()) {
                // 스태프 정보 저장
                movieMapper.insertCrewInfo(movieDtoList);
                // 영화-스태프 관계 정보 저장
                movieMapper.insertCrewMovieInfo(movieDtoList);
            }
    
            if (!crewImgList.isEmpty()) {
                // 스태프 프로필 이미지 저장
                movieMapper.insertFileInfo(crewImgList);
                // 스태프 프로필 이미지 저장
                movieMapper.insertCrewImg(crewImgList);
            }
    
        } catch (Exception e) {
            e.printStackTrace();
        }
        
    }

    @Override
    public int insertFileInfo(List<MovieDto> movieDto) {

        return movieMapper.insertFileInfo(movieDto);
    }
}