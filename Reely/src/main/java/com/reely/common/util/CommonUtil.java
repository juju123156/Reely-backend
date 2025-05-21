package com.reely.common.util;

import java.io.*;
import java.net.*;
import java.nio.file.*;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.UUID;


public class CommonUtil {

    public static void fileDownloader(String fileUrl, String saveDir, String fileName) {
        try (InputStream in = new URL(fileUrl).openStream()) {
            // 디렉토리 없으면 생성
            Files.createDirectories(Paths.get(saveDir));
            // 🔍 URL에서 파일 확장자 추출
            // 전체 경로 구성
            Path filePath = Paths.get(saveDir, fileName);
            // 파일 다운로드 및 저장
            Files.copy(in, filePath, StandardCopyOption.REPLACE_EXISTING);

            System.out.println("파일 다운로드 완료: " + filePath);
        } catch (IOException e) {
            System.err.println("다운로드 실패: " + e.getMessage());
            e.printStackTrace();
        }
    }


    public static void vodFileDownloader(String fileUrl, String saveDir, String fileName) {
        try {
            // 파일 다운로드
            try (InputStream in = new URL(fileUrl).openStream()) {
                // 디렉토리 없으면 생성
                Files.createDirectories(Paths.get(saveDir));
                // 전체 경로 구성
                Path filePath = Paths.get(saveDir, fileName);

                // 파일 다운로드 및 저장
                Files.copy(in, filePath, StandardCopyOption.REPLACE_EXISTING);

                System.out.println("파일 다운로드 완료: " + filePath);
            }
        } catch (IOException e) {
            System.err.println("다운로드 실패: " + e.getMessage());
            e.printStackTrace();
        }
    }

    public static String generateFileName(String extension) {
        // 오늘 날짜 포맷: yyyyMMdd
        String date = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyyMMdd"));
        // UUID 생성
        String uuid = UUID.randomUUID().toString();
        // 확장자 포함한 파일 이름 생성
        return date + "_" + uuid + "." + extension;
    }

    public static String getExtension(String fileName) {
        int dotIndex = fileName.lastIndexOf('.');
        if (dotIndex != -1 && dotIndex < fileName.length() - 1) {
            return fileName.substring(dotIndex + 1);
        }
        return ""; // 확장자가 없거나 잘못된 경우
    }
    
}
